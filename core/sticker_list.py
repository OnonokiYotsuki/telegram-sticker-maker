"""Export the current sticker list without transcoding."""
from __future__ import annotations

import json
import os
import shutil
from datetime import datetime
from typing import Any, Iterable, Mapping, Optional

from core.pack_output import unique_arcname


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
