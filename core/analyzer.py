import json
import os
import subprocess
from dataclasses import asdict, dataclass
from typing import Optional
from PIL import Image

from core.proc import ffprobe_bin, run_hidden

try:
    import pillow_heif

    pillow_heif.register_heif_opener()
except ImportError:
    pass


_ALPHA_PIX_TOKENS = (
    "alpha",
    "yuva",
    "rgba",
    "bgra",
    "argb",
    "abgr",
    "gbra",
    "ya8",
    "ya16",
)


def pix_fmt_has_alpha(pix_fmt: str) -> bool:
    """True for pixel formats that carry an alpha plane (not e.g. gbrp)."""
    p = (pix_fmt or "").lower()
    return any(token in p for token in _ALPHA_PIX_TOKENS)


def stream_has_alpha(stream: dict) -> bool:
    """VP9 in MKV/WebM often reports pix_fmt=yuv420p and puts alpha in tags."""
    if pix_fmt_has_alpha(str(stream.get("pix_fmt") or "")):
        return True
    tags = stream.get("tags") or {}
    if not isinstance(tags, dict):
        tags = {}
    for key, raw in tags.items():
        if str(key).lower() != "alpha_mode":
            continue
        val = str(raw).strip().lower()
        if val in ("1", "true", "yes", "on"):
            return True
    for item in stream.get("side_data_list") or []:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("side_data_type") or item.get("type") or "").lower()
        if "alpha" in kind:
            return True
    return False


def _parse_float(value) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_frame_rate(fps_str: str, default: float = 30.0) -> float:
    raw = (fps_str or "").strip() or f"{default}/1"
    if "/" in raw:
        num, den = raw.split("/", 1)
        parsed_den = _parse_float(den)
        parsed_num = _parse_float(num)
        if parsed_num is not None and parsed_den and parsed_den > 0:
            return round(parsed_num / parsed_den, 2)
        return default
    parsed = _parse_float(raw)
    return parsed if parsed is not None else default


@dataclass
class MediaInfo:
    file_path: str
    file_name: str
    file_size: int
    is_video: bool
    width: int
    height: int
    duration: float  # in seconds, 0.0 for static images
    fps: float
    has_alpha: bool
    format_name: str
    video_codec: str
    audio_codec: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)


class MediaAnalyzer:
    IMAGE_EXTENSIONS = {
        ".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff", ".tif", ".ico", ".heic", ".heif"
    }
    ANIMATED_OR_VIDEO_EXTENSIONS = {
        ".mp4", ".mov", ".mkv", ".webm", ".avi", ".flv", ".gif", ".apng", ".m4v"
    }
    MEDIA_EXTENSIONS = IMAGE_EXTENSIONS | ANIMATED_OR_VIDEO_EXTENSIONS

    @staticmethod
    def get_ffprobe_path() -> Optional[str]:
        return ffprobe_bin()

    @classmethod
    def analyze(cls, file_path: str) -> MediaInfo:
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")

        file_name = os.path.basename(file_path)
        file_size = os.path.getsize(file_path)
        ext = os.path.splitext(file_name)[1].lower()

        # Try ffprobe first for rich info
        ffprobe = cls.get_ffprobe_path()
        if ffprobe:
            try:
                cmd = [
                    ffprobe,
                    "-v", "quiet",
                    "-print_format", "json",
                    "-show_format",
                    "-show_streams",
                    file_path
                ]
                res = run_hidden(cmd, text=True, timeout=10)
                if res.returncode == 0 and res.stdout:
                    info_dict = json.loads(res.stdout)
                    return cls._parse_ffprobe_json(file_path, file_size, info_dict)
            except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError, ValueError):
                pass

        # Fallback to Pillow for images
        return cls._analyze_with_pillow(file_path, file_size)

    @classmethod
    def _parse_ffprobe_json(cls, file_path: str, file_size: int, data: dict) -> MediaInfo:
        streams = data.get("streams", [])
        format_info = data.get("format", {})

        video_stream = None
        audio_stream = None

        for s in streams:
            if s.get("codec_type") == "video" and video_stream is None:
                video_stream = s
            elif s.get("codec_type") == "audio" and audio_stream is None:
                audio_stream = s

        if video_stream is None:
            # Fallback to image if no video stream
            return cls._analyze_with_pillow(file_path, file_size)

        width = int(video_stream.get("width", 0))
        height = int(video_stream.get("height", 0))

        # FPS calculation
        fps = _parse_frame_rate(video_stream.get("r_frame_rate", "30/1"))
        duration_val = _parse_float(video_stream.get("duration")) or _parse_float(
            format_info.get("duration")
        ) or 0.0
        has_alpha = stream_has_alpha(video_stream)

        codec_name = video_stream.get("codec_name", "")
        format_name = format_info.get("format_name", "")
        nb_frames_raw = _parse_float(video_stream.get("nb_frames"))
        nb_frames = int(nb_frames_raw) if nb_frames_raw else 0
        is_animated_image = (
            codec_name in ("gif", "apng", "webp_anim")
            or format_name in ("gif", "apng", "webp_anim")
            or "webp_anim" in format_name
        )
        is_video = duration_val > 0.05 or nb_frames > 1 or is_animated_image

        # Enhance with Pillow for image formats (APNG, animated WebP, GIF, HEIC/HEIF)
        # ffprobe often leaves duration and nb_frames as None for APNG, and misses alpha/rotation on HEIC
        ext = os.path.splitext(file_path)[1].lower()
        if ext in (".gif", ".png", ".apng", ".webp", ".heic", ".heif") or is_animated_image:
            try:
                from PIL import ImageOps
                with Image.open(file_path) as pimg:
                    is_anim = getattr(pimg, "is_animated", False)
                    if is_anim:
                        is_video = True
                        n_frames = getattr(pimg, "n_frames", 1)
                        if duration_val <= 0.05:
                            total_dur_ms = 0
                            for frame in range(n_frames):
                                pimg.seek(frame)
                                total_dur_ms += pimg.info.get("duration", 100)
                            if total_dur_ms > 0:
                                duration_val = round(total_dur_ms / 1000.0, 3)
                        if fps <= 0 or fps > 100:
                            fps = round(n_frames / duration_val, 2) if duration_val > 0 else 30.0
                    if not has_alpha:
                        has_alpha = pimg.mode in ("RGBA", "LA") or (
                            pimg.mode == "P" and "transparency" in pimg.info
                        )
                    if ext in (".heic", ".heif"):
                        trans = ImageOps.exif_transpose(pimg)
                        width, height = trans.size
            except (OSError, ValueError, AttributeError):
                pass

        audio_codec = audio_stream.get("codec_name") if audio_stream else None

        return MediaInfo(
            file_path=file_path,
            file_name=os.path.basename(file_path),
            file_size=file_size,
            is_video=is_video,
            width=width,
            height=height,
            duration=duration_val,
            fps=fps,
            has_alpha=has_alpha,
            format_name=format_info.get("format_name", ""),
            video_codec=codec_name,
            audio_codec=audio_codec,
        )

    @classmethod
    def _analyze_with_pillow(cls, file_path: str, file_size: int) -> MediaInfo:
        from PIL import ImageOps
        with Image.open(file_path) as img:
            trans = ImageOps.exif_transpose(img)
            width, height = trans.size
            has_alpha = trans.mode in ("RGBA", "LA") or (
                trans.mode == "P" and "transparency" in trans.info
            )
            is_animated = getattr(trans, "is_animated", False)
            duration = 0.0
            if is_animated:
                total_duration_ms = 0
                n_frames = getattr(trans, "n_frames", 1)
                for frame in range(n_frames):
                    trans.seek(frame)
                    total_duration_ms += trans.info.get("duration", 100)
                duration = total_duration_ms / 1000.0

            fps = round(getattr(trans, "n_frames", 1) / duration, 2) if duration > 0 else 0.0

            return MediaInfo(
                file_path=file_path,
                file_name=os.path.basename(file_path),
                file_size=file_size,
                is_video=is_animated,
                width=width,
                height=height,
                duration=duration,
                fps=fps,
                has_alpha=has_alpha,
                format_name=img.format or "IMAGE",
                video_codec=img.format or "IMAGE",
                audio_codec=None,
            )
