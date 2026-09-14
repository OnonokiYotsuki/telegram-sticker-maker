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
