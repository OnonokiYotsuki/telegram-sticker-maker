"""Autosave the in-progress sticker list so the next launch can resume."""
from __future__ import annotations

import json
import os
from typing import Any, Iterable, Mapping

from core.app_paths import session_file
from core.sticker_list import build_sticker_list_document, _normalize_list_item


def session_path() -> str:
    return session_file()


def save_session(stickers: Iterable[Mapping[str, Any]], path: str | None = None) -> dict[str, Any]:
    dest = os.path.abspath(path or session_path())
    parent = os.path.dirname(dest)
    if parent:
        os.makedirs(parent, exist_ok=True)
    doc = build_sticker_list_document(stickers, export_mode="list")
    payload = json.dumps(doc, ensure_ascii=False, indent=2) + "\n"
    tmp = dest + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(payload)
    os.replace(tmp, dest)
    return {"path": dest, "count": len(doc["stickers"])}


def load_session(path: str | None = None) -> dict[str, Any]:
    source = os.path.abspath(path or session_path())
    if not os.path.isfile(source):
        return {"status": "empty", "stickers": [], "missing": [], "count": 0}

    try:
        with open(source, "r", encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return {"status": "empty", "stickers": [], "missing": [], "count": 0}

    if not isinstance(doc, dict) or not isinstance(doc.get("stickers"), list):
        return {"status": "empty", "stickers": [], "missing": [], "count": 0}

    root = os.path.dirname(source) or os.getcwd()
    stickers: list[dict[str, Any]] = []
    missing: list[str] = []
    for raw in doc["stickers"]:
        if not isinstance(raw, Mapping):
            continue
        original = str(raw.get("input_path") or "").strip()
        item = _normalize_list_item(raw, root)
        if item:
            stickers.append(item)
        elif original:
            missing.append(original)

    return {
        "status": "ok" if stickers else "empty",
        "stickers": stickers,
        "missing": missing,
        "count": len(stickers),
        "path": source,
    }
