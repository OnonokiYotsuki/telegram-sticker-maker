import base64
import io
import json
import os
import re
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, fields
from subprocess import TimeoutExpired
from typing import List, Optional, Tuple, Union
from PIL import Image, ImageOps

from core.proc import ffmpeg_bin, run_hidden


DEFAULT_PROMPT = (
    "Analyze this Telegram sticker/animation. "
    "Reply ONLY with 1 to 3 relevant facial expression or reaction emojis "
    "that best match the character's emotion for chat typing suggestions. "
    "Focus strictly on clear emotions (e.g. 😂, 😭, 😡, 🥺, 😴, 🤔, 👍). "
    "Do NOT use decorative, vibe, or generic symbols like ✨, 🌟, 💫, 🎀, 💖 "
    "unless the sticker literally portrays stars or glowing magic."
)


@dataclass
class AIEmojiConfig:
    api_key: str = ""
    base_url: str = "https://api.openai.com/v1"
    model: str = "gpt-4o-mini"
    prompt: str = DEFAULT_PROMPT
    use_emoji_naming: bool = True
    zero_pad: bool = True  # e.g., 001_😂 vs 1_😂

    @classmethod
    def get_config_dir(cls) -> str:
        from core.app_paths import config_dir

        return config_dir()

    @classmethod
    def get_config_path(cls) -> str:
        return os.path.join(cls.get_config_dir(), "ai_config.json")

    @classmethod
    def load(cls) -> "AIEmojiConfig":
        path = cls.get_config_path()
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if not isinstance(data, dict):
                    return cls()
                known = {f.name for f in fields(cls)}
                filtered = {k: v for k, v in data.items() if k in known}
                prompt = filtered.get("prompt", "")
                legacy_fragments = (
                    "capture its mood, emotion, character, or action",
                    "Analyze this sticker/image",
                )
                if any(frag in prompt for frag in legacy_fragments):
                    filtered["prompt"] = DEFAULT_PROMPT
                return cls(**filtered)
            except (OSError, json.JSONDecodeError, TypeError, ValueError):
                pass
        return cls()

    def save(self):
        path = self.get_config_path()
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(asdict(self), f, ensure_ascii=False, indent=2)
        except OSError:
            pass


class AIEmojiTagger:
    """
    AI-powered emoji extractor and output file namer for Telegram stickers/emojis.
    Uses OpenAI-compatible Vision Chat Completions (GPT-4o, Gemini, SiliconFlow, Ollama).
    """

    # Regex for standard unicode emojis
    EMOJI_PATTERN = re.compile(
        r"[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U00002300-\U000023FF\u200d\ufe0f]+"
    )

    DECORATIVE_EMOJIS = {"✨", "🌟", "💫"}

    @classmethod
    def extract_emojis(cls, text: str) -> str:
        """Extracts only unicode emoji characters from text."""
        if not text:
            return ""
        matches = cls.EMOJI_PATTERN.findall(text)
        if matches:
            return "".join(matches)[:12]
        return ""

    @classmethod
    def sanitize_emoji_string(cls, text: str) -> str:
        """Extracts clean emoji characters from text or strips invalid filename characters."""
        if not text:
            return ""
        emojis = cls.extract_emojis(text)
        if emojis:
            # Strip pure decorative symbols if other meaningful emojis are present
            filtered = "".join(c for c in emojis if c not in cls.DECORATIVE_EMOJIS)
            return filtered if filtered else emojis

        # If no emoji matched, strip illegal filename chars
        cleaned = re.sub(r'[\\/*?:"<>|\r\n\t]+', "", text).strip()
        return cleaned

    @classmethod
    def _create_storyboard_base64(cls, frames: list, max_dim: int = 256) -> str:
        """
        Creates a base64 JPEG from a list of frames.
        If multiple frames are provided, stitches them into a horizontal storyboard/filmstrip.
        """
        if not frames:
            return ""
        if len(frames) == 1:
            return cls._img_to_base64(frames[0], max_dim)

        target_h = min(max_dim, 200)
        processed = []
        for f in frames:
            f_rgba = f.convert("RGBA")
            bg = Image.new("RGBA", f_rgba.size, (255, 255, 255, 255))
            bg.paste(f_rgba, (0, 0), f_rgba)
            rgb_f = bg.convert("RGB")

            orig_w, orig_h = rgb_f.size
            if orig_h > 0:
                new_w = max(1, int(orig_w * (target_h / orig_h)))
            else:
                new_w = target_h
            rgb_f = rgb_f.resize((new_w, target_h), Image.Resampling.LANCZOS)
            processed.append(rgb_f)

        gap = 4
        total_w = sum(f.width for f in processed) + gap * (len(processed) - 1)
        filmstrip = Image.new("RGB", (total_w, target_h), (230, 230, 230))

        curr_x = 0
        for f in processed:
            filmstrip.paste(f, (curr_x, 0))
            curr_x += f.width + gap

        max_total_w = max_dim * 3
        if filmstrip.width > max_total_w:
            filmstrip.thumbnail((max_total_w, target_h), Image.Resampling.LANCZOS)

        buf = io.BytesIO()
        filmstrip.save(buf, format="JPEG", quality=80)
        return base64.b64encode(buf.getvalue()).decode("utf-8")

    @classmethod
    def _apply_frame_transforms(
        cls,
        img: Image.Image,
        crop: Optional[Union[Tuple[int, int, int, int], List[int]]] = None,
        crop_radius: float = 0.0,
        mirror: bool = False,
    ) -> Image.Image:
        """
        Applies mirror, crop, and crop_radius transforms to match sticker output.
        """
        from core.crop_shape import apply_crop_radius, normalize_crop_radius

        try:
            img = ImageOps.exif_transpose(img)
        except Exception:
            pass

        if mirror:
            img = ImageOps.mirror(img)

        if crop and len(crop) == 4:
            try:
                cx, cy, cw, ch = [int(v) for v in crop]
                if cw > 0 and ch > 0:
                    w, h = img.size
                    right = min(w, max(0, cx + cw))
                    bottom = min(h, max(0, cy + ch))
                    left = min(max(0, cx), max(0, right - 1))
                    top = min(max(0, cy), max(0, bottom - 1))
                    if right > left and bottom > top:
                        img = img.crop((left, top, right, bottom))
            except (TypeError, ValueError):
                pass

        if normalize_crop_radius(crop_radius) > 0.001:
            img = apply_crop_radius(img, crop_radius)

        return img

    @classmethod
    def extract_frame_base64(
        cls,
        file_path: str,
        max_dim: int = 256,
        start_time: Optional[float] = None,
        end_time: Optional[float] = None,
        crop: Optional[Union[Tuple[int, int, int, int], List[int]]] = None,
        crop_radius: float = 0.0,
        mirror: bool = False,
    ) -> Optional[str]:
        """
        Extracts a lightweight base64 JPEG from an image, animated image, or video file.
        For animated images and videos, extracts representative frames across the timeline
        and stitches them into a multi-frame storyboard to capture emotion and action progression.
        Applies crop, mirror, and crop_radius if specified so only the sticker area is analyzed.
        """
        if not os.path.exists(file_path):
            return None

        ext = os.path.splitext(file_path)[1].lower()

        # For videos, use ffmpeg to grab representative frames across duration
        if ext in (".mp4", ".mov", ".mkv", ".webm", ".avi", ".flv", ".m4v"):
            try:
                ffmpeg = ffmpeg_bin()
            except FileNotFoundError:
                return None

            if start_time is not None and end_time is not None and end_time > start_time:
                clip_dur = end_time - start_time
                if clip_dur >= 1.5:
                    timestamps = [
                        round(start_time + clip_dur * 0.2, 2),
                        round(start_time + clip_dur * 0.5, 2),
                        round(start_time + clip_dur * 0.8, 2),
                    ]
                elif clip_dur >= 0.6:
                    timestamps = [round(start_time + 0.1, 2), round(start_time + clip_dur * 0.6, 2)]
                else:
                    timestamps = [round(start_time + 0.1, 2)]
            else:
                duration = 0.0
                try:
                    from core.analyzer import MediaAnalyzer
                    info = MediaAnalyzer.analyze(file_path)
                    duration = info.duration
                except (OSError, ValueError):
                    pass

                if duration >= 1.5:
                    timestamps = [round(duration * 0.2, 2), round(duration * 0.5, 2), round(duration * 0.8, 2)]
                elif duration >= 0.6:
                    timestamps = [0.1, round(duration * 0.6, 2)]
                else:
                    timestamps = [0.1]

            frames = []
            for t in timestamps:
                try:
                    cmd = [
                        ffmpeg, "-y",
                        "-ss", str(t),
                        "-i", file_path,
                        "-vframes", "1",
                        "-f", "image2pipe",
                        "-vcodec", "mjpeg",
                        "pipe:1"
                    ]
                    res = run_hidden(cmd, timeout=5)
                    if res.returncode == 0 and res.stdout:
                        frame = Image.open(io.BytesIO(res.stdout))
                        frame = cls._apply_frame_transforms(
                            frame, crop=crop, crop_radius=crop_radius, mirror=mirror
                        )
                        frames.append(frame)
                except (OSError, TimeoutExpired, ValueError):
                    pass

            if frames:
                return cls._create_storyboard_base64(frames, max_dim)
            return None

        # For images (PNG, APNG, WebP, GIF, JPG)
        try:
            with Image.open(file_path) as img:
                is_anim = getattr(img, "is_animated", False)
                n_frames = getattr(img, "n_frames", 1)
                if is_anim and n_frames > 1:
                    if n_frames == 2:
                        indices = [0, 1]
                    elif n_frames == 3:
                        indices = [0, 1, 2]
                    else:
                        indices = [
                            max(0, int(n_frames * 0.2)),
                            int(n_frames * 0.5),
                            min(n_frames - 1, int(n_frames * 0.8)),
                        ]
                        indices = sorted(list(set(indices)))

                    frames = []
                    for idx in indices:
                        img.seek(idx)
                        frame = img.copy()
                        frame = cls._apply_frame_transforms(
                            frame, crop=crop, crop_radius=crop_radius, mirror=mirror
                        )
                        frames.append(frame)
                    return cls._create_storyboard_base64(frames, max_dim)
                else:
                    frame = img.copy()
                    frame = cls._apply_frame_transforms(
                        frame, crop=crop, crop_radius=crop_radius, mirror=mirror
                    )
                    return cls._img_to_base64(frame, max_dim)
        except (OSError, ValueError):
            return None

    @classmethod
    def _img_to_base64(cls, img: Image.Image, max_dim: int) -> str:
        img = img.convert("RGBA")
        img.thumbnail((max_dim, max_dim), Image.Resampling.LANCZOS)
        # Paste onto white background to handle transparency cleanly for vision models
        bg = Image.new("RGBA", img.size, (255, 255, 255, 255))
        bg.paste(img, (0, 0), img)
        rgb_img = bg.convert("RGB")
        buf = io.BytesIO()
        rgb_img.save(buf, format="JPEG", quality=80)
        return base64.b64encode(buf.getvalue()).decode("utf-8")

    @classmethod
    def predict_emoji(
        cls,
        file_path: str,
        config: AIEmojiConfig,
        max_retries: int = 2,
        timeout: int = 25,
        start_time: Optional[float] = None,
        end_time: Optional[float] = None,
        crop: Optional[Union[Tuple[int, int, int, int], List[int]]] = None,
        crop_radius: float = 0.0,
        mirror: bool = False,
    ) -> str:
        """
        Calls the vision completion endpoint to predict matching emojis.
        Includes timeout tolerance (25s) and retry backoff on transient errors.
        Returns empty string if the API is unconfigured or unavailable.
        """
        is_local = "localhost" in config.base_url or "127.0.0.1" in config.base_url
        if not config.api_key.strip() and not is_local:
            return ""

        b64_data = cls.extract_frame_base64(
            file_path,
            start_time=start_time,
            end_time=end_time,
            crop=crop,
            crop_radius=crop_radius,
            mirror=mirror,
        )
        if not b64_data:
            return ""

        headers = {
            "Content-Type": "application/json",
        }
        if config.api_key.strip():
            headers["Authorization"] = f"Bearer {config.api_key.strip()}"

        endpoint = f"{config.base_url.rstrip('/')}/chat/completions"

        payload = {
            "model": config.model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": config.prompt,
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{b64_data}"
                            },
                        },
                    ],
                }
            ],
            "max_tokens": 32,
            "temperature": 0.2,
        }

        for attempt in range(max_retries + 1):
            try:
                req = urllib.request.Request(
                    endpoint,
                    data=json.dumps(payload).encode("utf-8"),
                    headers=headers,
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    result = json.loads(resp.read().decode("utf-8"))
                    content = result["choices"][0]["message"]["content"].strip()
                    emojis = cls.sanitize_emoji_string(content)
                    if emojis:
                        return emojis
                # If model returned text with no valid emoji, do not keep retrying
                break
            except urllib.error.HTTPError as e:
                # Permanent client errors (400, 401, 403, 404) should fail immediately
                if e.code in (400, 401, 403, 404):
                    break
                # Temporary server / rate-limit errors (429, 500, 502, 503, 504) -> retry
                if attempt < max_retries:
                    time.sleep(1.0 * (attempt + 1))
                    continue
            except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError, KeyError, IndexError):
                if attempt < max_retries:
                    time.sleep(1.0 * (attempt + 1))
                    continue

        return ""

    @classmethod
    def format_output_name(
        cls,
        index: int,
        emojis: str,
        ext: str,
        zero_pad: bool = True,
        use_emoji_naming: bool = True,
        original_name: str = "",
    ) -> str:
        """
        Formats output filename based on user requirement: {index}_{emojis}{ext}
        e.g., 001_😂.webm or 1_😂.webm
        """
        if not ext.startswith("."):
            ext = "." + ext

        if not use_emoji_naming:
            clean_orig = re.sub(r'[\\/*?:"<>|\r\n\t]+', "", original_name).strip()
            return f"{clean_orig}{ext}" if clean_orig else f"sticker_{index}{ext}"

        # Format index
        idx_str = f"{index:03d}" if zero_pad else str(index)
        clean_emojis = cls.sanitize_emoji_string(emojis)

        if clean_emojis:
            return f"{idx_str}_{clean_emojis}{ext}"
        else:
            return f"{idx_str}{ext}"

    @classmethod
    def test_connection(cls, config: AIEmojiConfig) -> Tuple[bool, str]:
        """Tests if the API endpoint and key work properly."""
        is_local = "localhost" in config.base_url or "127.0.0.1" in config.base_url
        if not config.api_key.strip() and not is_local:
            return False, "API Key 不能为空！"

        # Create a tiny 1x1 test image
        test_img = Image.new("RGB", (16, 16), (255, 200, 0))
        buf = io.BytesIO()
        test_img.save(buf, format="JPEG")
        b64_data = base64.b64encode(buf.getvalue()).decode("utf-8")

        headers = {
            "Content-Type": "application/json",
        }
        if config.api_key.strip():
            headers["Authorization"] = f"Bearer {config.api_key.strip()}"

        endpoint = f"{config.base_url.rstrip('/')}/chat/completions"
        payload = {
            "model": config.model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Reply with one emoji."},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64_data}"}},
                    ],
                }
            ],
            "max_tokens": 5,
        }

        try:
            req = urllib.request.Request(
                endpoint,
                data=json.dumps(payload).encode("utf-8"),
                headers=headers,
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                reply = data["choices"][0]["message"]["content"]
                return True, f"连接成功！模型回复: {reply}"
        except urllib.error.HTTPError as e:
            return False, f"HTTP 错误 {e.code}: {e.reason}"
        except urllib.error.URLError as e:
            return False, f"网络连接失败: {e.reason}"
        except Exception as e:
            return False, f"请求异常: {str(e)}"
