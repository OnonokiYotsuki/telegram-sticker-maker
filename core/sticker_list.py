"""Export the current sticker list without transcoding."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import zipfile
from datetime import datetime
from typing import Any, Callable, Iterable, Mapping, Optional

ExportProgressCb = Callable[..., None]
ExportCancelCheck = Callable[[], bool]

from PIL import Image

from core.crop_shape import apply_crop_radius, build_radius_mask_filter, normalize_crop_radius
from core.pack_output import (
    STICKERS_JSON_NAME,
    PackEntry,
    build_stickers_manifest,
    normalize_keywords,
    pack_stickers,
    unique_arcname,
)
from core.proc import ffmpeg_bin, run_hidden


LIST_KIND = "sticker_maker_list"
LIST_VERSION = 1
BUNDLE_JSON_NAME = "sticker_list.json"
BUNDLE_SOURCES_DIR = "sources"


class StickerListError(ValueError):
    """Raised when the sticker list cannot be exported or imported."""


def default_list_name(now: Optional[datetime] = None) -> str:
    stamp = (now or datetime.now()).strftime("%Y%m%d_%H%M%S")
    return f"sticker_list_{stamp}.json"


def default_bundle_name(now: Optional[datetime] = None) -> str:
    stamp = (now or datetime.now()).strftime("%Y%m%d_%H%M%S")
    return f"sticker_bundle_{stamp}"


def default_bundle_zip_name(now: Optional[datetime] = None) -> str:
    return f"{default_bundle_name(now)}.zip"


def zip_directory(src_dir: str, zip_path: str) -> dict[str, Any]:
    root = os.path.abspath(src_dir)
    dest = os.path.abspath(zip_path)
    if not dest.lower().endswith(".zip"):
        dest += ".zip"
    parent = os.path.dirname(dest)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with zipfile.ZipFile(dest, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as zf:
        for dirpath, _, filenames in os.walk(root):
            for name in sorted(filenames):
                full = os.path.join(dirpath, name)
                arc = os.path.relpath(full, root).replace("\\", "/")
                zf.write(full, arcname=arc)
    return {"path": dest, "bytes": os.path.getsize(dest)}


def _as_optional_float(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_crop(value: Any) -> Optional[list[int]]:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return None
    try:
        return [int(value[0]), int(value[1]), int(value[2]), int(value[3])]
    except (TypeError, ValueError):
        return None


def build_sticker_list_document(
    stickers: Iterable[Mapping[str, Any]],
    *,
    export_mode: str = "list",
) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    for raw in stickers:
        path = str(raw.get("input_path") or "").strip()
        if not path:
            continue
        item: dict[str, Any] = {
            "input_path": path,
            "file_name": str(raw.get("file_name") or os.path.basename(path)),
            "is_video": bool(raw.get("is_video", True)),
            "emoji": str(raw.get("emoji") or ""),
            "keywords": str(raw.get("keywords") or ""),
        }
        start_time = _as_optional_float(raw.get("start_time"))
        end_time = _as_optional_float(raw.get("end_time"))
        if start_time is not None:
            item["start_time"] = start_time
        if end_time is not None:
            item["end_time"] = end_time
        crop = _as_crop(raw.get("crop"))
        if crop is not None:
            item["crop"] = crop
        radius = _as_optional_float(raw.get("crop_radius"))
        if radius is not None and radius > 0.001:
            item["crop_radius"] = max(0.0, min(1.0, radius))
        for key in ("clip_group_id", "clip_id", "clip_label"):
            val = str(raw.get(key) or "").strip()
            if val:
                item[key] = val
        items.append(item)
    mode = "sources" if export_mode == "sources" else "list"
    return {
        "kind": LIST_KIND,
        "version": LIST_VERSION,
        "export_mode": mode,
        "exported_at": datetime.now().isoformat(timespec="seconds"),
        "stickers": items,
    }


def write_sticker_list(
    path: str,
    stickers: Iterable[Mapping[str, Any]],
    *,
    export_mode: str = "list",
) -> dict[str, Any]:
    dest = os.path.abspath(path)
    if not dest.lower().endswith(".json"):
        dest += ".json"
    parent = os.path.dirname(dest)
    if parent:
        os.makedirs(parent, exist_ok=True)
    doc = build_sticker_list_document(stickers, export_mode=export_mode)
    if not doc["stickers"]:
        raise StickerListError("贴纸列表为空")
    with open(dest, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    return {"path": dest, "count": len(doc["stickers"])}


def _raise_if_canceled(cancel_check: Optional[ExportCancelCheck]) -> None:
    if cancel_check and cancel_check():
        raise StickerListError("已取消导出")


def write_sticker_bundle(
    dest_dir: str,
    stickers: Iterable[Mapping[str, Any]],
    *,
    zip_path: str = "",
    progress_callback: Optional[ExportProgressCb] = None,
    cancel_check: Optional[ExportCancelCheck] = None,
) -> dict[str, Any]:
    """Copy unique source files and write a JSON list with relative paths."""
    root = os.path.abspath(dest_dir)
    sources_dir = os.path.join(root, BUNDLE_SOURCES_DIR)
    os.makedirs(sources_dir, exist_ok=True)

    used: set[str] = set()
    path_map: dict[str, str] = {}
    missing: list[str] = []
    remapped: list[dict[str, Any]] = []
    rows = [raw for raw in stickers if str(raw.get("input_path") or "").strip()]
    total = len(rows)
    report_item_path = not bool(zip_path)

    for i, raw in enumerate(rows, 1):
        _raise_if_canceled(cancel_check)
        src = os.path.abspath(str(raw.get("input_path") or "").strip())
        if progress_callback:
            progress_callback(i, total, raw, phase="start")
        if src not in path_map:
            if not os.path.isfile(src):
                missing.append(src)
                if progress_callback:
                    progress_callback(i, total, raw, phase="skip")
                continue
            name = unique_arcname(os.path.basename(src), used)
            copied = os.path.join(sources_dir, name)
            shutil.copy2(src, copied)
            path_map[src] = f"{BUNDLE_SOURCES_DIR}/{name}"
        rel = path_map[src]
        item = dict(raw)
        item["input_path"] = rel
        item["file_name"] = os.path.basename(rel)
        remapped.append(item)
        abs_copied = os.path.join(root, rel.replace("/", os.sep))
        size = os.path.getsize(abs_copied) if os.path.isfile(abs_copied) else 0
        if progress_callback:
            progress_callback(
                i,
                total,
                raw,
                phase="done",
                dest=abs_copied if report_item_path else "",
                size=size,
            )

    if not remapped:
        raise StickerListError("没有可复制的源文件")

    json_path = os.path.join(root, BUNDLE_JSON_NAME)
    written = write_sticker_list(json_path, remapped, export_mode="sources")
    result: dict[str, Any] = {
        "path": root,
        "json_path": written["path"],
        "count": written["count"],
        "copied": len(path_map),
        "missing": missing,
    }
    if zip_path:
        _raise_if_canceled(cancel_check)
        if progress_callback:
            progress_callback(len(remapped), max(total, 1), {}, phase="pack")
        packed = zip_directory(root, zip_path)
        result["path"] = packed["path"]
        result["zip_path"] = packed["path"]
        result["bytes"] = packed["bytes"]
    return result


def format_prepared_name(index: int, emoji: str, ext: str) -> str:
    if not ext.startswith("."):
        ext = "." + ext
    idx = f"{int(index):03d}"
    clean = (emoji or "").strip()
    return f"{idx}_{clean}{ext}" if clean else f"{idx}{ext}"


def _normalized_crop(crop: list[int]) -> tuple[int, int, int, int]:
    cx, cy, cw, ch = (int(crop[0]), int(crop[1]), int(crop[2]), int(crop[3]))
    cw = max(2, cw - (cw % 2))
    ch = max(2, ch - (ch % 2))
    cx = max(0, cx - (cx % 2))
    cy = max(0, cy - (cy % 2))
    return cx, cy, cw, ch


def prepared_output_ext(
    src: str,
    *,
    is_video: bool,
    crop: Optional[list[int]],
    radius: float,
) -> str:
    orig = os.path.splitext(src)[1] or ".bin"
    if is_video:
        return orig
    if not crop:
        return orig
    if normalize_crop_radius(radius) > 0.001:
        return ".png"
    if orig.lower() in {".png", ".jpg", ".jpeg", ".webp"}:
        return orig
    return ".png"


def should_copy_whole_file(
    is_video: bool,
    start_time: Optional[float],
    end_time: Optional[float],
    duration: Optional[float],
) -> bool:
    if not is_video:
        return True
    start = float(start_time or 0)
    if start > 0.05:
        return False
    if end_time is None:
        return True
    end = float(end_time)
    if end <= start:
        return True
    if duration is not None and end >= float(duration) - 0.05:
        return True
    return False


def extract_source_clip(
    input_path: str,
    output_path: str,
    *,
    is_video: bool = True,
    start_time: Optional[float] = None,
    end_time: Optional[float] = None,
    duration: Optional[float] = None,
    crop: Optional[list[int]] = None,
    crop_radius: float = 0.0,
) -> None:
    """Cut/copy a clip. Applies crop shape when given (requires a light encode)."""
    src = os.path.abspath(input_path)
    dest = os.path.abspath(output_path)
    if not os.path.isfile(src):
        raise StickerListError(f"源文件不存在: {src}")
    os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
    if src == dest and not crop:
        return
    if crop:
        if is_video:
            _extract_video_with_crop(
                src,
                dest,
                start_time=start_time,
                end_time=end_time,
                crop=crop,
                crop_radius=crop_radius,
            )
        else:
            _extract_image_with_crop(src, dest, crop=crop, crop_radius=crop_radius)
        return
    if should_copy_whole_file(is_video, start_time, end_time, duration):
        if src != dest:
            shutil.copy2(src, dest)
        return

    start = float(start_time or 0)
    end = float(end_time) if end_time is not None else None
    clip_dur = (end - start) if end is not None and end > start else None
    ffmpeg = ffmpeg_bin()

    def run_copy(with_map: bool) -> bool:
        if os.path.isfile(dest):
            os.remove(dest)
        cmd = [ffmpeg, "-y"]
        if start > 0.02:
            cmd += ["-ss", f"{start:.3f}"]
        cmd += ["-i", src]
        if clip_dur is not None:
            cmd += ["-t", f"{clip_dur:.3f}"]
        cmd += ["-c", "copy", "-avoid_negative_ts", "make_zero", "-fflags", "+genpts"]
        if with_map:
            cmd += ["-map", "0"]
        cmd += [dest]
        res = run_hidden(cmd)
        return res.returncode == 0 and os.path.isfile(dest) and os.path.getsize(dest) > 512

    if run_copy(False) or run_copy(True):
        return
    shutil.copy2(src, dest)


def _extract_image_with_crop(
    src: str,
    dest: str,
    crop: list[int],
    crop_radius: float,
) -> None:
    cx, cy, cw, ch = _normalized_crop(crop)
    with Image.open(src) as img:
        w, h = img.size
        right = min(w, cx + cw)
        bottom = min(h, cy + ch)
        left = min(max(0, cx), max(0, right - 2))
        top = min(max(0, cy), max(0, bottom - 2))
        cropped = img.crop((left, top, right, bottom))
        if normalize_crop_radius(crop_radius) > 0.001:
            cropped = apply_crop_radius(cropped, crop_radius)
        ext = os.path.splitext(dest)[1].lower()
        save_kw: dict[str, Any] = {}
        if ext in {".jpg", ".jpeg"}:
            cropped = cropped.convert("RGB")
            save_kw["quality"] = 95
        cropped.save(dest, **save_kw)
    if not os.path.isfile(dest) or os.path.getsize(dest) == 0:
        raise StickerListError("裁切图片失败")


def _extract_video_with_crop(
    src: str,
    dest: str,
    *,
    start_time: Optional[float],
    end_time: Optional[float],
    crop: list[int],
    crop_radius: float,
) -> None:
    cx, cy, cw, ch = _normalized_crop(crop)
    vf = f"crop={cw}:{ch}:{cx}:{cy}"
    radius = normalize_crop_radius(crop_radius)
    mask = build_radius_mask_filter(radius)
    if mask:
        vf = f"{vf},{mask}"
    start = float(start_time or 0)
    end = float(end_time) if end_time is not None else None
    clip_dur = (end - start) if end is not None and end > start else None
    ffmpeg = ffmpeg_bin()
    cmd = [ffmpeg, "-y"]
    if start > 0.02:
        cmd += ["-ss", f"{start:.3f}"]
    cmd += ["-i", src]
    if clip_dur is not None:
        cmd += ["-t", f"{clip_dur:.3f}"]
    cmd += ["-vf", vf, "-an", "-sn", "-dn", "-map_metadata", "-1"]
    ext = os.path.splitext(dest)[1].lower()
    if mask and ext in {".webm", ".mkv"}:
        cmd += [
            "-c:v",
            "libvpx-vp9",
            "-pix_fmt",
            "yuva420p",
            "-crf",
            "30",
            "-b:v",
            "0",
            "-auto-alt-ref",
            "0",
        ]
    else:
        cmd += ["-c:v", "libx264", "-preset", "fast", "-crf", "18", "-pix_fmt", "yuv420p"]
        if ext in {".mp4", ".m4v", ".mov"}:
            cmd += ["-movflags", "+faststart"]
    cmd.append(dest)
    if os.path.isfile(dest):
        os.remove(dest)
    res = run_hidden(cmd)
    if res.returncode != 0 or not os.path.isfile(dest) or os.path.getsize(dest) < 512:
        err = (res.stderr or b"")[-300:]
        if isinstance(err, bytes):
            err = err.decode("utf-8", "replace")
        raise StickerListError(f"裁切视频失败: {err}")


def export_prepared_stickers(
    stickers: Iterable[Mapping[str, Any]],
    dest_dir: str,
    *,
    zip_path: str = "",
    progress_callback: Optional[ExportProgressCb] = None,
    cancel_check: Optional[ExportCancelCheck] = None,
) -> dict[str, Any]:
    """Export conversion-named files without transcoding. Optionally zip like convert."""
    root = os.path.abspath(dest_dir)
    os.makedirs(root, exist_ok=True)
    used: set[str] = set()
    entries: list[PackEntry] = []
    missing: list[str] = []
    rows = [raw for raw in stickers if str(raw.get("input_path") or "").strip()]
    total = len(rows)
    report_item_path = not bool(zip_path)

    for i, raw in enumerate(rows, 1):
        _raise_if_canceled(cancel_check)
        src = str(raw.get("input_path") or "").strip()
        if progress_callback:
            progress_callback(i, total, raw, phase="start")
        if not os.path.isfile(src):
            missing.append(src)
            if progress_callback:
                progress_callback(i, total, raw, phase="skip")
            continue
        index = int(raw.get("index") or i)
        emoji = str(raw.get("emoji") or "")
        is_video = bool(raw.get("is_video", True))
        crop = _as_crop(raw.get("crop"))
        radius = _as_optional_float(raw.get("crop_radius")) or 0.0
        ext = prepared_output_ext(src, is_video=is_video, crop=crop, radius=radius)
        name = unique_arcname(format_prepared_name(index, emoji, ext), used)
        out_path = os.path.join(root, name)
        try:
            extract_source_clip(
                src,
                out_path,
                is_video=is_video,
                start_time=_as_optional_float(raw.get("start_time")),
                end_time=_as_optional_float(raw.get("end_time")),
                duration=_as_optional_float(raw.get("duration")),
                crop=crop,
                crop_radius=radius,
            )
        except Exception as exc:
            if progress_callback:
                progress_callback(i, total, raw, phase="error", error=str(exc))
            raise
        size = os.path.getsize(out_path) if os.path.isfile(out_path) else 0
        entries.append(
            PackEntry(
                path=out_path,
                emoji=emoji,
                keywords=raw.get("keywords"),
                arcname=name,
            )
        )
        if progress_callback:
            progress_callback(
                i,
                total,
                raw,
                phase="done",
                dest=out_path if report_item_path else "",
                size=size,
            )

    if not entries:
        raise StickerListError("没有可导出的源文件")

    manifest_path = os.path.join(root, STICKERS_JSON_NAME)
    with open(manifest_path, "w", encoding="utf-8") as fh:
        json.dump(build_stickers_manifest(entries), fh, ensure_ascii=False, indent=2)
        fh.write("\n")

    result: dict[str, Any] = {
        "path": root,
        "count": len(entries),
        "missing": missing,
        "files": [item.arcname for item in entries],
        "json_path": manifest_path,
    }
    if zip_path:
        _raise_if_canceled(cancel_check)
        if progress_callback:
            progress_callback(len(entries), max(total, 1), {}, phase="pack")
        packed = pack_stickers(entries, zip_path, allow_any_file=True)
        result["path"] = packed["path"]
        result["zip_path"] = packed["path"]
        result["bytes"] = packed["bytes"]
    return result


def keywords_to_str(value: Any) -> str:
    return ", ".join(normalize_keywords(value))


def find_import_manifest(root: str) -> str:
    root = os.path.abspath(root)
    for name in (BUNDLE_JSON_NAME, STICKERS_JSON_NAME):
        candidate = os.path.join(root, name)
        if os.path.isfile(candidate):
            return candidate
    try:
        for entry in sorted(os.listdir(root)):
            child = os.path.join(root, entry)
            if not os.path.isdir(child):
                continue
            for name in (BUNDLE_JSON_NAME, STICKERS_JSON_NAME):
                candidate = os.path.join(child, name)
                if os.path.isfile(candidate):
                    return candidate
    except OSError:
        return ""
    return ""


def looks_like_import_path(path: str) -> bool:
    raw = (path or "").strip()
    if not raw:
        return False
    lower = raw.lower()
    if lower.endswith(".zip") or lower.endswith(".json"):
        return True
    return os.path.isdir(raw) and bool(find_import_manifest(raw))


def _import_cache_root() -> str:
    return os.path.join(tempfile.gettempdir(), "tg_sticker_maker_imports")


def extract_zip_for_import(zip_path: str) -> str:
    source = os.path.abspath(zip_path)
    st = os.stat(source)
    key = hashlib.sha1(f"{source}:{st.st_mtime_ns}:{st.st_size}".encode("utf-8")).hexdigest()[:12]
    stem = os.path.splitext(os.path.basename(source))[0] or "bundle"
    dest = os.path.join(_import_cache_root(), f"{stem}_{key}")
    marker = os.path.join(dest, ".ok")
    if os.path.isfile(marker) and find_import_manifest(dest):
        return dest
    os.makedirs(dest, exist_ok=True)
    with zipfile.ZipFile(source, "r") as zf:
        zf.extractall(dest)
    with open(marker, "w", encoding="utf-8") as fh:
        fh.write(source)
    return dest


def resolve_import_media_path(root: str, raw_path: str) -> str:
    raw = str(raw_path or "").strip()
    if not raw:
        return ""
    if os.path.isfile(raw):
        return os.path.abspath(raw)
    rel = raw.replace("\\", "/").lstrip("/")
    joined = os.path.abspath(os.path.join(root, *rel.split("/")))
    if os.path.isfile(joined):
        return joined
    nested = os.path.join(root, os.path.basename(rel))
    if os.path.isfile(nested):
        return os.path.abspath(nested)
    return ""


def _normalize_list_item(raw: Mapping[str, Any], root: str) -> Optional[dict[str, Any]]:
    src = resolve_import_media_path(root, str(raw.get("input_path") or ""))
    if not src:
        return None
    item: dict[str, Any] = {
        "input_path": src,
        "file_name": str(raw.get("file_name") or os.path.basename(src)),
        "emoji": str(raw.get("emoji") or ""),
        "keywords": keywords_to_str(raw.get("keywords")),
    }
    if "is_video" in raw:
        item["is_video"] = bool(raw.get("is_video"))
    start_time = _as_optional_float(raw.get("start_time"))
    end_time = _as_optional_float(raw.get("end_time"))
    if start_time is not None:
        item["start_time"] = start_time
    if end_time is not None:
        item["end_time"] = end_time
    crop = _as_crop(raw.get("crop"))
    if crop is not None:
        item["crop"] = crop
    radius = _as_optional_float(raw.get("crop_radius"))
    if radius is not None and radius > 0.001:
        item["crop_radius"] = max(0.0, min(1.0, radius))
    for key in ("clip_group_id", "clip_id", "clip_label"):
        val = str(raw.get(key) or "").strip()
        if val:
            item[key] = val
    return item


def _normalize_pack_item(raw: Mapping[str, Any], root: str) -> Optional[dict[str, Any]]:
    src = resolve_import_media_path(root, str(raw.get("file") or raw.get("input_path") or ""))
    if not src:
        return None
    return {
        "input_path": src,
        "file_name": str(raw.get("file") or os.path.basename(src)),
        "emoji": str(raw.get("emoji") or ""),
        "keywords": keywords_to_str(raw.get("keywords")),
    }


def import_sticker_bundle(path: str) -> dict[str, Any]:
    """Load an exported folder, zip, or JSON back into sticker specs."""
    source = os.path.abspath((path or "").strip())
    if not source or not os.path.exists(source):
        raise StickerListError("找不到导入文件")

    if os.path.isfile(source) and source.lower().endswith(".zip"):
        root = extract_zip_for_import(source)
        manifest = find_import_manifest(root)
    elif os.path.isfile(source) and source.lower().endswith(".json"):
        manifest = source
        root = os.path.dirname(source) or os.getcwd()
    elif os.path.isdir(source):
        manifest = find_import_manifest(source)
        root = os.path.dirname(manifest) if manifest else source
    else:
        raise StickerListError("请选择导出的 zip、JSON 或文件夹")

    if not manifest:
        raise StickerListError("未找到 sticker_list.json 或 stickers.json")

    try:
        with open(manifest, "r", encoding="utf-8") as fh:
            doc = json.load(fh)
    except Exception as exc:
        raise StickerListError(f"无法读取列表文件: {exc}") from exc

    if not isinstance(doc, dict) or not isinstance(doc.get("stickers"), list):
        raise StickerListError("列表文件格式无效")

    is_maker_list = doc.get("kind") == LIST_KIND or "export_mode" in doc
    mode = "sources" if doc.get("export_mode") == "sources" else "list"
    stickers: list[dict[str, Any]] = []
    missing: list[str] = []
    for raw in doc["stickers"]:
        if not isinstance(raw, Mapping):
            continue
        if is_maker_list or "input_path" in raw:
            original = str(raw.get("input_path") or "").strip()
            item = _normalize_list_item(raw, root)
        else:
            original = str(raw.get("file") or raw.get("input_path") or "").strip()
            item = _normalize_pack_item(raw, root)
        if item:
            stickers.append(item)
        elif original:
            missing.append(original)

    if not stickers:
        raise StickerListError("没有可导入的贴纸文件")

    return {
        "mode": mode,
        "count": len(stickers),
        "stickers": stickers,
        "missing": missing,
        "json_path": os.path.abspath(manifest),
        "root": os.path.abspath(root),
    }
