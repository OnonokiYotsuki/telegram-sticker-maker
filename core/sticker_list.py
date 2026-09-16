"""Export the current sticker list without transcoding."""
from __future__ import annotations

import json
import os
import shutil
from datetime import datetime
from typing import Any, Iterable, Mapping, Optional

from core.pack_output import PackEntry, pack_stickers, unique_arcname
from core.proc import ffmpeg_bin, run_hidden


LIST_KIND = "sticker_maker_list"
LIST_VERSION = 1
BUNDLE_JSON_NAME = "sticker_list.json"
BUNDLE_SOURCES_DIR = "sources"


class StickerListError(ValueError):
    """Raised when the sticker list cannot be exported."""


def default_list_name(now: Optional[datetime] = None) -> str:
    stamp = (now or datetime.now()).strftime("%Y%m%d_%H%M%S")
    return f"sticker_list_{stamp}.json"


def default_bundle_name(now: Optional[datetime] = None) -> str:
    stamp = (now or datetime.now()).strftime("%Y%m%d_%H%M%S")
    return f"sticker_bundle_{stamp}"


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


def write_sticker_bundle(dest_dir: str, stickers: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Copy unique source files and write a JSON list with relative paths."""
    root = os.path.abspath(dest_dir)
    sources_dir = os.path.join(root, BUNDLE_SOURCES_DIR)
    os.makedirs(sources_dir, exist_ok=True)

    used: set[str] = set()
    path_map: dict[str, str] = {}
    missing: list[str] = []
    remapped: list[dict[str, Any]] = []
    rows = list(stickers)

    for raw in rows:
        src = os.path.abspath(str(raw.get("input_path") or "").strip())
        if not src:
            continue
        if src not in path_map:
            if not os.path.isfile(src):
                missing.append(src)
                continue
            name = unique_arcname(os.path.basename(src), used)
            shutil.copy2(src, os.path.join(sources_dir, name))
            path_map[src] = f"{BUNDLE_SOURCES_DIR}/{name}"
        item = dict(raw)
        item["input_path"] = path_map[src]
        item["file_name"] = os.path.basename(path_map[src])
        remapped.append(item)

    if not remapped:
        raise StickerListError("没有可复制的源文件")

    json_path = os.path.join(root, BUNDLE_JSON_NAME)
    written = write_sticker_list(json_path, remapped, export_mode="sources")
    return {
        "path": root,
        "json_path": written["path"],
        "count": written["count"],
        "copied": len(path_map),
        "missing": missing,
    }


def format_prepared_name(index: int, emoji: str, ext: str) -> str:
    if not ext.startswith("."):
        ext = "." + ext
    idx = f"{int(index):03d}"
    clean = (emoji or "").strip()
    return f"{idx}_{clean}{ext}" if clean else f"{idx}{ext}"


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
) -> None:
    """Copy or stream-copy a clip. Does not transcode."""
    src = os.path.abspath(input_path)
    dest = os.path.abspath(output_path)
    if not os.path.isfile(src):
        raise StickerListError(f"源文件不存在: {src}")
    os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
    if src == dest:
        return
    if should_copy_whole_file(is_video, start_time, end_time, duration):
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


def export_prepared_stickers(
    stickers: Iterable[Mapping[str, Any]],
    dest_dir: str,
    *,
    zip_path: str = "",
) -> dict[str, Any]:
    """Export conversion-named files without transcoding. Optionally zip like convert."""
    root = os.path.abspath(dest_dir)
    os.makedirs(root, exist_ok=True)
    used: set[str] = set()
    entries: list[PackEntry] = []
    missing: list[str] = []

    for i, raw in enumerate(stickers, 1):
        src = str(raw.get("input_path") or "").strip()
        if not src:
            continue
        if not os.path.isfile(src):
            missing.append(src)
            continue
        index = int(raw.get("index") or i)
        emoji = str(raw.get("emoji") or "")
        ext = os.path.splitext(src)[1] or ".bin"
        name = unique_arcname(format_prepared_name(index, emoji, ext), used)
        out_path = os.path.join(root, name)
        extract_source_clip(
            src,
            out_path,
            is_video=bool(raw.get("is_video", True)),
            start_time=_as_optional_float(raw.get("start_time")),
            end_time=_as_optional_float(raw.get("end_time")),
            duration=_as_optional_float(raw.get("duration")),
        )
        entries.append(
            PackEntry(
                path=out_path,
                emoji=emoji,
                keywords=raw.get("keywords"),
                arcname=name,
            )
        )

    if not entries:
        raise StickerListError("没有可导出的源文件")

    result: dict[str, Any] = {
        "path": root,
        "count": len(entries),
        "missing": missing,
        "files": [item.arcname for item in entries],
    }
    if zip_path:
        packed = pack_stickers(entries, zip_path, allow_any_file=True)
        result["path"] = packed["path"]
        result["zip_path"] = packed["path"]
        result["bytes"] = packed["bytes"]
    return result
