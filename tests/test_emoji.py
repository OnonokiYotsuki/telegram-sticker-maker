import os
import pytest
from PIL import Image
from core.analyzer import MediaAnalyzer
from core.encoder import EncodeOptions, StickerEncoder


@pytest.fixture
def sample_static_image(tmp_path):
    img_path = str(tmp_path / "test_emoji_static.png")
    img = Image.new("RGBA", (300, 200), (100, 150, 250, 255))
    img.save(img_path)
    return img_path


@pytest.fixture
def sample_animated_image(tmp_path):
    gif_path = str(tmp_path / "test_emoji_anim.gif")
    frames = []
    for i in range(10):
        img = Image.new("RGBA", (150, 100), (i * 25, 200, 100, 220))
        frames.append(img)
    frames[0].save(
        gif_path,
        save_all=True,
        append_images=frames[1:],
        duration=100,
        loop=0,
    )
    return gif_path


def test_static_custom_emoji_conversion(sample_static_image, tmp_path):
    out_webp = str(tmp_path / "emoji_static.webp")
    opts = EncodeOptions(is_custom_emoji=True)

    success = StickerEncoder.convert(sample_static_image, out_webp, opts)
    assert success is True
    assert os.path.exists(out_webp)
    assert os.path.getsize(out_webp) <= 64 * 1024

    info = MediaAnalyzer.analyze(out_webp)
    assert info.width == 100
    assert info.height == 100


def test_animated_custom_emoji_conversion(sample_animated_image, tmp_path):
    out_webm = str(tmp_path / "emoji_anim.webm")
    opts = EncodeOptions(is_custom_emoji=True)

    success = StickerEncoder.convert(sample_animated_image, out_webm, opts)
    assert success is True
    assert os.path.exists(out_webm)
    assert os.path.getsize(out_webm) <= 64 * 1024

    info = MediaAnalyzer.analyze(out_webm)
    assert info.width == 100
    assert info.height == 100
    assert info.fps == 10.0
