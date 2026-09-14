"""Bundle converted stickers into a ZIP."""
from __future__ import annotations

import os
import zipfile
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, Optional


STICKER_EXTS = {".webm", ".webp"}


@dataclass(frozen=True)
class PackEntry:
    path: str
    emoji: str = ""
    arcname: str = ""


class PackError(ValueError):
    """Raised when there is nothing valid to pack."""


def default_zip_name(now: Optional[datetime] = None) -> str:
    stamp = (now or datetime.now()).strftime("%Y%m%d_%H%M%S")
    return f"TG_Stickers_{stamp}.zip"


def unique_arcname(name: str, used: set[str]) -> str:
    base = os.path.basename(name.replace("\\", "/")).strip() or "sticker"
    if base not in used:
        used.add(base)
        return base
    stem, ext = os.path.splitext(base)
    stem = stem or "sticker"
    i = 2
    while True:
        candidate = f"{stem}_{i}{ext}"
        if candidate not in used:
            used.add(candidate)
            return candidate
        i += 1


def resolve_entries(entries: Iterable[PackEntry]) -> list[PackEntry]:
    used: set[str] = set()
    resolved: list[PackEntry] = []
    for entry in entries:
        path = os.path.abspath(entry.path)
        if not os.path.isfile(path):
            continue
        ext = os.path.splitext(path)[1].lower()
        if ext not in STICKER_EXTS:
            continue
        arc = unique_arcname(entry.arcname or os.path.basename(path), used)
        resolved.append(PackEntry(path=path, emoji=(entry.emoji or "").strip(), arcname=arc))
    return resolved


def pack_stickers(entries: Iterable[PackEntry], zip_path: str) -> dict:
    """Write sticker files into a zip. Returns pack stats."""
    resolved = resolve_entries(entries)
    if not resolved:
        raise PackError("没有可打包的贴纸文件")

    zip_path = os.path.abspath(zip_path)
    os.makedirs(os.path.dirname(zip_path) or ".", exist_ok=True)

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as zf:
        for item in resolved:
            zf.write(item.path, arcname=item.arcname)

    return {
        "path": zip_path,
        "count": len(resolved),
        "bytes": os.path.getsize(zip_path),
    }
