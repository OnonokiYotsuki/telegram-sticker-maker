import configparser
import os
from typing import Any, Dict, Optional

from core.ai_tagger import AIEmojiConfig


def default_output_dir() -> str:
    return os.path.join(os.path.expanduser("~"), "Desktop", "TG_Stickers")


def default_settings() -> Dict[str, Any]:
    return {
        "preset_style": "anime",
        "spoof_duration": True,
        "optimize_fps": True,
        "is_custom_emoji": False,
        "same_dir": False,
        "pack_output": True,
        "custom_output_dir": default_output_dir(),
        "use_emoji_naming": True,
        "zero_pad": True,
        "small_step_sec": 0.5,
        "large_step_sec": 5.0,
        "default_crop_aspect": "1:1",
        "default_crop_radius": 0.0,
        "show_timeline_overview": True,
        "playback_rate": 1.0,
        "ai_base_url": "https://api.openai.com/v1",
        "ai_model": "gpt-4o-mini",
        "ai_api_key": "",
    }


def settings_path() -> str:
    return os.path.join(AIEmojiConfig.get_config_dir(), "settings.ini")


def _load_ini(path: Optional[str] = None) -> configparser.ConfigParser:
    parser = configparser.ConfigParser()
    parser.optionxform = str
    target = path or settings_path()
    if os.path.isfile(target):
        parser.read(target, encoding="utf-8")
    return parser


def _ensure_section(parser: configparser.ConfigParser, section: str) -> None:
    if not parser.has_section(section):
        parser.add_section(section)


def _get(parser: configparser.ConfigParser, section: str, key: str, default: str = "") -> str:
    for sec in (section, "General", "%General"):
        if parser.has_section(sec) and parser.has_option(sec, key):
            return parser.get(sec, key)
    if parser.has_option("DEFAULT", key):
        return parser.get("DEFAULT", key)
    return default


def _as_bool(value: Any, default: bool = False) -> bool:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("true", "1", "yes", "on")


def _as_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


_CROP_ASPECTS = {"1:1", "free", "original", "16:9", "4:3", "9:16"}
_PLAYBACK_RATES = (0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 3.0, 4.0)
_CLIP_DIALOG_KEYS = (
    "small_step_sec",
    "large_step_sec",
    "default_crop_aspect",
    "default_crop_radius",
    "show_timeline_overview",
    "playback_rate",
)


def _as_playback_rate(value: Any, default: float = 1.0) -> float:
    rate = _as_float(value, default)
    return min(_PLAYBACK_RATES, key=lambda r: abs(r - rate))


def _as_crop_aspect(value: Any, default: str = "1:1") -> str:
    raw = str(value or "").strip()
    return raw if raw in _CROP_ASPECTS else default


def load_settings() -> Dict[str, Any]:
    defaults = default_settings()
    parser = _load_ini()
    ai_cfg = AIEmojiConfig.load()

    custom_out = (
        _get(parser, "settings", "custom_output_dir")
        or _get(parser, "General", "output_dir")
        or defaults["custom_output_dir"]
    )

    loaded = {
        "preset_style": _get(parser, "settings", "preset_style", defaults["preset_style"])
        or defaults["preset_style"],
        "spoof_duration": _as_bool(
            _get(parser, "settings", "spoof_duration", "true"), defaults["spoof_duration"]
        ),
        "optimize_fps": _as_bool(
            _get(parser, "settings", "optimize_fps", "true"), defaults["optimize_fps"]
        ),
        "is_custom_emoji": _as_bool(
            _get(parser, "settings", "is_custom_emoji", "false"), defaults["is_custom_emoji"]
        ),
        "same_dir": _as_bool(
            _get(parser, "settings", "same_dir") or _get(parser, "General", "same_dir", "false"),
            defaults["same_dir"],
        ),
        "pack_output": _as_bool(
            _get(parser, "settings", "pack_output", "true"), defaults["pack_output"]
        ),
        "custom_output_dir": str(custom_out),
        "use_emoji_naming": _as_bool(
            _get(parser, "settings", "use_emoji_naming", "true"), defaults["use_emoji_naming"]
        ),
        "zero_pad": _as_bool(_get(parser, "settings", "zero_pad", "true"), defaults["zero_pad"]),
        "small_step_sec": _as_float(
            _get(parser, "clip_dialog", "small_step_sec", "0.5"), defaults["small_step_sec"]
        ),
        "large_step_sec": _as_float(
            _get(parser, "clip_dialog", "large_step_sec", "5.0"), defaults["large_step_sec"]
        ),
        "default_crop_aspect": _as_crop_aspect(
            _get(parser, "clip_dialog", "default_crop_aspect", defaults["default_crop_aspect"]),
            defaults["default_crop_aspect"],
        ),
        "default_crop_radius": max(
            0.0,
            min(
                1.0,
                _as_float(
                    _get(parser, "clip_dialog", "default_crop_radius", "0"),
                    defaults["default_crop_radius"],
                ),
            ),
        ),
        "show_timeline_overview": _as_bool(
            _get(parser, "clip_dialog", "show_timeline_overview", "true"),
            defaults["show_timeline_overview"],
        ),
        "playback_rate": _as_playback_rate(
            _get(parser, "clip_dialog", "playback_rate", "1"),
            defaults["playback_rate"],
        ),
        "ai_base_url": ai_cfg.base_url
        or _get(parser, "ai", "base_url", defaults["ai_base_url"])
        or defaults["ai_base_url"],
        "ai_model": ai_cfg.model
        or _get(parser, "ai", "model", defaults["ai_model"])
        or defaults["ai_model"],
        "ai_api_key": ai_cfg.api_key or _get(parser, "ai", "api_key", ""),
    }
    return {**defaults, **loaded}


def save_settings(data: Dict[str, Any]) -> None:
    path = settings_path()
    parser = _load_ini(path)
    for k, v in data.items():
        if k in _CLIP_DIALOG_KEYS:
            _ensure_section(parser, "clip_dialog")
            parser.set("clip_dialog", k, str(v))
        elif k.startswith("ai_"):
            _ensure_section(parser, "ai")
            parser.set("ai", k[3:], str(v))
        else:
            _ensure_section(parser, "settings")
            val_str = str(v).lower() if isinstance(v, bool) else str(v)
            parser.set("settings", k, val_str)
            if k == "same_dir":
                _ensure_section(parser, "General")
                parser.set("General", "same_dir", val_str)
            elif k == "custom_output_dir":
                _ensure_section(parser, "General")
                parser.set("General", "output_dir", val_str)

    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        parser.write(f)

    if any(k.startswith("ai_") for k in data):
        cfg = AIEmojiConfig.load()
        if "ai_api_key" in data:
            cfg.api_key = str(data.get("ai_api_key") or "")
        if "ai_base_url" in data:
            cfg.base_url = str(data.get("ai_base_url") or cfg.base_url)
        if "ai_model" in data:
            cfg.model = str(data.get("ai_model") or cfg.model)
        cfg.save()
