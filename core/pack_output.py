"""Bundle converted stickers into a ZIP."""
from __future__ import annotations

import json
import os
import re
import zipfile
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable, Optional

from core.crop_shape import crop_radius_label, normalize_crop_radius


STICKER_EXTS = {".webm", ".webp"}
STICKERS_JSON_NAME = "stickers.json"
MAX_KEYWORDS = 20
MAX_KEYWORDS_CHARS = 64
_KEYWORD_SPLIT_RE = re.compile(r"[,，、;；\s]+")


def normalize_keywords(value: Any) -> tuple[str, ...]:
    """Parse keywords from a string or sequence. Telegram allows 0-20, total 64 chars."""
    if value is None:
        parts: list[str] = []
    elif isinstance(value, (list, tuple)):
        parts = [str(item) for item in value]
    else:
        parts = _KEYWORD_SPLIT_RE.split(str(value))

    out: list[str] = []
    seen: set[str] = set()
    total = 0
    for raw in parts:
        word = raw.strip()
        if not word or word in seen:
            continue
        if len(out) >= MAX_KEYWORDS:
            break
        room = MAX_KEYWORDS_CHARS - total
        if room <= 0:
            break
        if len(word) > room:
            word = word[:room]
            if not word or word in seen:
                break
        seen.add(word)
        out.append(word)
        total += len(word)
    return tuple(out)


@dataclass(frozen=True)
class PackEntry:
    path: str
    emoji: str = ""
    keywords: tuple[str, ...] = ()
    arcname: str = ""
    crop_radius: float = 0.0
    proxy: str = ""

    def __post_init__(self):
        object.__setattr__(self, "emoji", (self.emoji or "").strip())
        object.__setattr__(self, "keywords", normalize_keywords(self.keywords))
        object.__setattr__(self, "crop_radius", normalize_crop_radius(self.crop_radius))


class PackError(ValueError):
    """Raised when there is nothing valid to pack."""


def default_zip_name(now: Optional[datetime] = None) -> str:
    stamp = (now or datetime.now()).strftime("%Y%m%d_%H%M%S")
    return f"TG_Stickers_{stamp}.zip"


def default_pack_dir_name(now: Optional[datetime] = None) -> str:
    return os.path.splitext(default_zip_name(now))[0]


def unique_output_dir(parent: str, name: str = "") -> str:
    """Create `parent/name`, appending _2, _3... if the path already exists."""
    parent = os.path.abspath(parent or ".")
    os.makedirs(parent, exist_ok=True)
    folder = (name or "").strip() or default_pack_dir_name()
    dest = os.path.join(parent, folder)
    if not os.path.exists(dest):
        os.makedirs(dest)
        return dest
    i = 2
    while True:
        candidate = os.path.join(parent, f"{folder}_{i}")
        if not os.path.exists(candidate):
            os.makedirs(candidate)
            return candidate
        i += 1


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


def resolve_entries(
    entries: Iterable[PackEntry],
    allow_any_file: bool = False,
) -> list[PackEntry]:
    used: set[str] = {STICKERS_JSON_NAME}
    resolved: list[PackEntry] = []
    for entry in entries:
        path = os.path.abspath(entry.path)
        if not os.path.isfile(path):
            continue
        ext = os.path.splitext(path)[1].lower()
        if not allow_any_file and ext not in STICKER_EXTS:
            continue
        arc = unique_arcname(entry.arcname or os.path.basename(path), used)
        resolved.append(
            PackEntry(
                path=path,
                emoji=(entry.emoji or "").strip(),
                keywords=normalize_keywords(entry.keywords),
                arcname=arc,
                crop_radius=entry.crop_radius,
                proxy=(entry.proxy or "").replace("\\", "/").strip(),
            )
        )
    return resolved


def build_stickers_manifest(entries: Iterable[PackEntry]) -> dict:
    stickers = []
    for item in entries:
        row: dict[str, Any] = {
            "file": item.arcname,
            "emoji": item.emoji or "",
            "keywords": list(item.keywords),
            "crop_radius": round(item.crop_radius, 4),
            "shape": crop_radius_label(item.crop_radius),
        }
        if item.proxy:
            row["proxy"] = item.proxy.replace("\\", "/")
        stickers.append(row)
    return {"stickers": stickers}


def pack_stickers(
    entries: Iterable[PackEntry],
    zip_path: str,
    allow_any_file: bool = False,
    extra_files: Optional[Iterable[tuple[str, str]]] = None,
) -> dict:
    """Write sticker files into a zip. Returns pack stats."""
    resolved = resolve_entries(entries, allow_any_file=allow_any_file)
    if not resolved:
        raise PackError("没有可打包的贴纸文件")

    zip_path = os.path.abspath(zip_path)
    os.makedirs(os.path.dirname(zip_path) or ".", exist_ok=True)
    manifest = build_stickers_manifest(resolved)
    payload = json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8")

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as zf:
        for item in resolved:
            zf.write(item.path, arcname=item.arcname)
        zf.writestr(STICKERS_JSON_NAME, payload)
        used = {STICKERS_JSON_NAME, *(item.arcname for item in resolved)}
        for extra_path, extra_arc in extra_files or []:
            if not extra_path or not os.path.isfile(extra_path):
                continue
            arc = (extra_arc or os.path.basename(extra_path)).replace("\\", "/").lstrip("/")
            if not arc or arc in used:
                continue
            zf.write(extra_path, arcname=arc)
            used.add(arc)

    return {
        "path": zip_path,
        "count": len(resolved),
        "bytes": os.path.getsize(zip_path),
        "manifest": STICKERS_JSON_NAME,
    }
