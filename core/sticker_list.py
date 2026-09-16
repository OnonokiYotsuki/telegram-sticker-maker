"""Export the current sticker list without transcoding."""
from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any, Iterable, Mapping, Optional


LIST_KIND = "sticker_maker_list"
LIST_VERSION = 1


class StickerListError(ValueError):
    """Raised when the sticker list cannot be exported."""


def default_list_name(now: Optional[datetime] = None) -> str:
    stamp = (now or datetime.now()).strftime("%Y%m%d_%H%M%S")
    return f"sticker_list_{stamp}.json"


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


def build_sticker_list_document(stickers: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
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
    return {
        "kind": LIST_KIND,
        "version": LIST_VERSION,
        "exported_at": datetime.now().isoformat(timespec="seconds"),
        "stickers": items,
    }


def write_sticker_list(path: str, stickers: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    dest = os.path.abspath(path)
    if not dest.lower().endswith(".json"):
        dest += ".json"
    parent = os.path.dirname(dest)
    if parent:
        os.makedirs(parent, exist_ok=True)
    doc = build_sticker_list_document(stickers)
    if not doc["stickers"]:
        raise StickerListError("贴纸列表为空")
    with open(dest, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    return {"path": dest, "count": len(doc["stickers"])}
