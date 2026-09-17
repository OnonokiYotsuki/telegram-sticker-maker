"""Config vs data directories.

`settings.ini` / `ai_config.json` stay in the well-known config dir so the
app can always find them. Session, preview proxies, and import unzip cache
live together under `data_dir` (default: the same config dir).
"""
from __future__ import annotations

import configparser
import os
import shutil
import tempfile
from typing import Optional

SESSION_FILENAME = "session.json"
PROXIES_DIRNAME = "proxies"
IMPORTS_DIRNAME = "imports"

_CONFIG_DIR_OVERRIDE: Optional[str] = None
_DATA_DIR_OVERRIDE: Optional[str] = None
_LEGACY_MIGRATED = False


def set_config_dir_override(path: Optional[str]) -> None:
    """Test helper. Pass None to restore the real config dir."""
    global _CONFIG_DIR_OVERRIDE
    _CONFIG_DIR_OVERRIDE = os.path.abspath(path) if path else None
    if _CONFIG_DIR_OVERRIDE:
        os.makedirs(_CONFIG_DIR_OVERRIDE, exist_ok=True)


def set_data_dir_override(path: Optional[str]) -> None:
    """Test helper. Pass None to restore settings.ini / default."""
    global _DATA_DIR_OVERRIDE
    _DATA_DIR_OVERRIDE = os.path.abspath(path) if path else None
    if _DATA_DIR_OVERRIDE:
        os.makedirs(_DATA_DIR_OVERRIDE, exist_ok=True)


def config_dir() -> str:
    if _CONFIG_DIR_OVERRIDE:
        os.makedirs(_CONFIG_DIR_OVERRIDE, exist_ok=True)
        return _CONFIG_DIR_OVERRIDE
    path = os.path.join(os.path.expanduser("~"), ".config", "telegram_sticker_maker")
    os.makedirs(path, exist_ok=True)
    return path


def settings_ini_path() -> str:
    return os.path.join(config_dir(), "settings.ini")


def _read_configured_data_dir() -> str:
    if _DATA_DIR_OVERRIDE:
        return _DATA_DIR_OVERRIDE
    parser = configparser.ConfigParser()
    parser.optionxform = str
    ini = settings_ini_path()
    if os.path.isfile(ini):
        parser.read(ini, encoding="utf-8")
        raw = ""
        if parser.has_section("settings") and parser.has_option("settings", "data_dir"):
            raw = parser.get("settings", "data_dir")
        raw = os.path.expanduser((raw or "").strip())
        if raw:
            return os.path.abspath(raw)
    return config_dir()


def _ensure_data_layout(root: str) -> str:
    os.makedirs(root, exist_ok=True)
    os.makedirs(os.path.join(root, PROXIES_DIRNAME), exist_ok=True)
    os.makedirs(os.path.join(root, IMPORTS_DIRNAME), exist_ok=True)
    return os.path.abspath(root)


def _move_dir_contents(src: str, dest: str) -> None:
    if not os.path.isdir(src) or os.path.normcase(os.path.abspath(src)) == os.path.normcase(
        os.path.abspath(dest)
    ):
        return
    os.makedirs(dest, exist_ok=True)
    try:
        names = os.listdir(src)
    except OSError:
        return
    if not names:
        return
    for name in names:
        from_path = os.path.join(src, name)
        to_path = os.path.join(dest, name)
        if os.path.exists(to_path):
            continue
        try:
            shutil.move(from_path, to_path)
        except OSError:
            pass


def _migrate_legacy_temp_caches(root: str) -> None:
    global _LEGACY_MIGRATED
    if _LEGACY_MIGRATED or _CONFIG_DIR_OVERRIDE or _DATA_DIR_OVERRIDE:
        return
    if os.path.normcase(root) != os.path.normcase(config_dir()):
        return
    _LEGACY_MIGRATED = True
    tmp = tempfile.gettempdir()
    _move_dir_contents(os.path.join(tmp, "tg_sticker_maker_proxies"), os.path.join(root, PROXIES_DIRNAME))
    _move_dir_contents(os.path.join(tmp, "tg_sticker_maker_imports"), os.path.join(root, IMPORTS_DIRNAME))


def data_dir() -> str:
    wanted = _read_configured_data_dir()
    try:
        root = _ensure_data_layout(wanted)
    except OSError:
        root = _ensure_data_layout(config_dir())
    _migrate_legacy_temp_caches(root)
    return root


def session_file() -> str:
    return os.path.join(data_dir(), SESSION_FILENAME)


def proxy_dir() -> str:
    path = os.path.join(data_dir(), PROXIES_DIRNAME)
    os.makedirs(path, exist_ok=True)
    return path


def import_dir() -> str:
    path = os.path.join(data_dir(), IMPORTS_DIRNAME)
    os.makedirs(path, exist_ok=True)
    return path


def apply_data_dir_change(previous: str) -> str:
    """After settings.ini is written: copy session if the new folder has none."""
    current = data_dir()
    prev = os.path.abspath(previous) if previous else ""
    if prev and os.path.normcase(prev) != os.path.normcase(current):
        old_session = os.path.join(prev, SESSION_FILENAME)
        new_session = os.path.join(current, SESSION_FILENAME)
        if os.path.isfile(old_session) and not os.path.isfile(new_session):
            try:
                shutil.copy2(old_session, new_session)
            except OSError:
                pass
    return current
