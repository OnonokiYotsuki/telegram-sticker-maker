import os
import pytest
from PIL import Image
from core.analyzer import MediaAnalyzer
from core.encoder import EncodeOptions, StickerEncoder


@pytest.fixture
def sample_animated_gif(tmp_path):
    gif_path = str(tmp_path / "test_anim.gif")
    frames = []
    for i in range(5):
        img = Image.new("RGBA", (100, 100), (i * 40, 100, 200, 200))
        frames.append(img)
    frames[0].save(
        gif_path,
        save_all=True,
        append_images=frames[1:],
        duration=100,
        loop=0,
    )
    return gif_path


def test_animated_gif_conversion(sample_animated_gif, tmp_path):
    out_webm = str(tmp_path / "sticker_anim.webm")
    info = MediaAnalyzer.analyze(sample_animated_gif)
    assert info.is_video is True
    assert info.duration > 0

    success = StickerEncoder.convert(sample_animated_gif, out_webm, EncodeOptions())
    assert success is True
    assert os.path.exists(out_webm)
    assert os.path.getsize(out_webm) <= 256 * 1024
