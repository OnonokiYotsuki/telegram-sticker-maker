import os
import pytest
from PIL import Image
from core.ai_tagger import AIEmojiConfig, AIEmojiTagger


def test_format_output_name():
    # 1. Standard zero-padded emoji format
    name1 = AIEmojiTagger.format_output_name(
        index=1, emojis="😂", ext=".webm", zero_pad=True, use_emoji_naming=True
    )
    assert name1 == "001_😂.webm"

    # 2. Multiple emojis
    name2 = AIEmojiTagger.format_output_name(
        index=25, emojis="🐱❤️", ext=".webp", zero_pad=True, use_emoji_naming=True
    )
    assert name2 == "025_🐱❤️.webp"

    # 3. Non zero-padded
    name3 = AIEmojiTagger.format_output_name(
        index=3, emojis="🔥", ext=".webm", zero_pad=False, use_emoji_naming=True
    )
    assert name3 == "3_🔥.webm"

    # 4. Empty emoji fallback
    name4 = AIEmojiTagger.format_output_name(
        index=2, emojis="", ext=".webm", zero_pad=True, use_emoji_naming=True
    )
    assert name4 == "002.webm"

    # 5. Disabled emoji naming (fallback to original name)
    name5 = AIEmojiTagger.format_output_name(
        index=1,
        emojis="😂",
        ext=".webm",
        zero_pad=True,
        use_emoji_naming=False,
        original_name="my_cool_sticker",
    )
    assert name5 == "my_cool_sticker.webm"


def test_sanitize_emoji_string():
    # Valid emojis
    assert AIEmojiTagger.sanitize_emoji_string("😂🐱") == "😂🐱"
    # Text with emojis
    assert AIEmojiTagger.sanitize_emoji_string("Hello 😂 world 🐱") == "😂🐱"
    # Decorative emojis like ✨ stripped when accompanied by emotion emojis
    assert AIEmojiTagger.sanitize_emoji_string("😂✨") == "😂"
    assert AIEmojiTagger.sanitize_emoji_string("✨") == "✨"
    # Illegal filename characters stripped if plain text
    assert AIEmojiTagger.sanitize_emoji_string('dog/cat*smile?') == "dogcatsmile"


def test_extract_frame_base64(tmp_path):
    # Static image
    img_path = str(tmp_path / "test_frame.png")
    img = Image.new("RGBA", (100, 100), (255, 0, 0, 255))
    img.save(img_path)

    b64 = AIEmojiTagger.extract_frame_base64(img_path)
    assert b64 is not None
    assert len(b64) > 50

    # Animated GIF storyboard (multi-frame)
    gif_path = str(tmp_path / "test_anim.gif")
    frames = [
        Image.new("RGBA", (80, 80), (255, 0, 0, 255)),
        Image.new("RGBA", (80, 80), (0, 255, 0, 255)),
        Image.new("RGBA", (80, 80), (0, 0, 255, 255)),
        Image.new("RGBA", (80, 80), (255, 255, 0, 255)),
    ]
    frames[0].save(gif_path, save_all=True, append_images=frames[1:], duration=100)
    b64_anim = AIEmojiTagger.extract_frame_base64(gif_path)
    assert b64_anim is not None
    assert len(b64_anim) > len(b64) * 0.8  # Contains stitched multi-frame sequence

    # Animated WebP storyboard (multi-frame)
    webp_path = str(tmp_path / "test_anim.webp")
    frames[0].save(webp_path, save_all=True, append_images=frames[1:], duration=100)
    b64_webp = AIEmojiTagger.extract_frame_base64(webp_path)
    assert b64_webp is not None


def test_config_serialization(tmp_path, monkeypatch):
    cfg_dir = str(tmp_path / "config")
    monkeypatch.setattr(AIEmojiConfig, "get_config_dir", classmethod(lambda cls: cfg_dir))

    cfg = AIEmojiConfig(
        api_key="test-key-123",
        base_url="https://api.test.com/v1",
        model="test-vision-model",
        use_emoji_naming=True,
        zero_pad=True,
    )
    cfg.save()

    loaded = AIEmojiConfig.load()
    assert loaded.api_key == "test-key-123"
    assert loaded.base_url == "https://api.test.com/v1"
    assert loaded.model == "test-vision-model"


def test_prompt_migration(tmp_path, monkeypatch):
    cfg_dir = str(tmp_path / "config_mig")
    monkeypatch.setattr(AIEmojiConfig, "get_config_dir", classmethod(lambda cls: cfg_dir))

    cfg = AIEmojiConfig()
    cfg.prompt = "Analyze this sticker/image. Capture its mood, emotion, character, or action."
    cfg.save()

    loaded = AIEmojiConfig.load()
    assert "Telegram sticker" in loaded.prompt


def test_config_ignores_unknown_keys(tmp_path, monkeypatch):
    cfg_dir = str(tmp_path / "config_extra")
    monkeypatch.setattr(AIEmojiConfig, "get_config_dir", classmethod(lambda cls: cfg_dir))
    os.makedirs(cfg_dir, exist_ok=True)
    path = os.path.join(cfg_dir, "ai_config.json")
    with open(path, "w", encoding="utf-8") as f:
        f.write('{"api_key": "k", "unknown_future_field": true, "model": "x"}')
    loaded = AIEmojiConfig.load()
    assert loaded.api_key == "k"
    assert loaded.model == "x"


def test_extract_frame_with_crop(tmp_path):
    import base64
    import io

    # 1. Create a 200x200 image where:
    # Left half (0..99) is Red (255, 0, 0)
    # Right half (100..199) is Blue (0, 0, 255)
    img_path = str(tmp_path / "split.png")
    img = Image.new("RGBA", (200, 200), (255, 0, 0, 255))
    blue_block = Image.new("RGBA", (100, 200), (0, 0, 255, 255))
    img.paste(blue_block, (100, 0))
    img.save(img_path)

    # Crop the right half (blue side only)
    b64 = AIEmojiTagger.extract_frame_base64(img_path, crop=[100, 0, 100, 200], max_dim=256)
    assert b64 is not None
    decoded = Image.open(io.BytesIO(base64.b64decode(b64)))
    # Width and height of the decoded image should preserve aspect ratio of the crop (100x200)
    assert decoded.width < decoded.height
    # The center pixel should be blue (not red)
    center_color = decoded.getpixel((decoded.width // 2, decoded.height // 2))
    assert center_color[0] < 50 and center_color[2] > 200


def test_extract_frame_with_mirror_and_crop(tmp_path):
    import base64
    import io

    # Left half is Red, Right half is Blue
    img_path = str(tmp_path / "split_mirror.png")
    img = Image.new("RGBA", (200, 200), (255, 0, 0, 255))
    blue_block = Image.new("RGBA", (100, 200), (0, 0, 255, 255))
    img.paste(blue_block, (100, 0))
    img.save(img_path)

    # Mirror first: blue flips to left half (0..100)
    # Then crop left half (0, 0, 100, 200)
    b64 = AIEmojiTagger.extract_frame_base64(
        img_path, crop=[0, 0, 100, 200], mirror=True, max_dim=256
    )
    assert b64 is not None
    decoded = Image.open(io.BytesIO(base64.b64decode(b64)))
    center_color = decoded.getpixel((decoded.width // 2, decoded.height // 2))
    # Due to mirror, left half is now blue!
    assert center_color[0] < 50 and center_color[2] > 200


def test_extract_frame_with_crop_radius(tmp_path):
    import base64
    import io

    # Solid red square (100x100)
    img_path = str(tmp_path / "circle.png")
    img = Image.new("RGBA", (100, 100), (255, 0, 0, 255))
    img.save(img_path)

    # Crop to circle (crop_radius=1.0)
    b64 = AIEmojiTagger.extract_frame_base64(
        img_path, crop=[0, 0, 100, 100], crop_radius=1.0, max_dim=256
    )
    assert b64 is not None
    decoded = Image.open(io.BytesIO(base64.b64decode(b64)))
    # Corner pixel (0, 0) should be white (masked out and pasted on white bg)
    corner = decoded.getpixel((0, 0))
    assert corner[0] > 240 and corner[1] > 240 and corner[2] > 240
    # Center pixel should still be red
    center = decoded.getpixel((decoded.width // 2, decoded.height // 2))
    assert center[0] > 200 and center[1] < 50


def test_predict_emoji_passes_crop_params(monkeypatch):
    called = {}
    def mock_extract(file_path, max_dim=256, start_time=None, end_time=None, crop=None, crop_radius=0.0, mirror=False):
        called["crop"] = crop
        called["crop_radius"] = crop_radius
        called["mirror"] = mirror
        return "fake_b64"

    monkeypatch.setattr(AIEmojiTagger, "extract_frame_base64", classmethod(lambda cls, *a, **kw: mock_extract(*a, **kw)))

    cfg = AIEmojiConfig(api_key="sk-test", base_url="https://api.openai.com/v1")
    AIEmojiTagger.predict_emoji(
        "dummy.png",
        cfg,
        start_time=1.0,
        end_time=3.0,
        crop=[10, 20, 30, 40],
        crop_radius=0.8,
        mirror=True,
    )
    assert called["crop"] == [10, 20, 30, 40]
    assert called["crop_radius"] == 0.8
    assert called["mirror"] is True


def test_extract_video_frame_with_crop(tmp_path):
    import subprocess
    import base64
    import io
    from core.proc import ffmpeg_bin

    try:
        ffmpeg = ffmpeg_bin()
    except FileNotFoundError:
        pytest.skip("ffmpeg not available")

    vpath = str(tmp_path / "test_video.mp4")
    cmd = [
        ffmpeg, "-y",
        "-f", "lavfi",
        "-i", "testsrc=duration=2:size=320x240:rate=24",
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        vpath,
    ]
    subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)

    b64 = AIEmojiTagger.extract_frame_base64(
        vpath,
        start_time=0.0,
        end_time=1.0,
        crop=[0, 0, 100, 100],
        crop_radius=0.0,
        max_dim=256,
    )
    assert b64 is not None
    decoded = Image.open(io.BytesIO(base64.b64decode(b64)))
    assert decoded.width > 0 and decoded.height > 0
