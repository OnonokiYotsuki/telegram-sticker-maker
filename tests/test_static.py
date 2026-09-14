import os
import pytest
from PIL import Image
from core.analyzer import MediaAnalyzer
from core.encoder import EncodeOptions, StickerEncoder


@pytest.fixture
def sample_image(tmp_path):
    # Generate a test RGBA image
    img_path = str(tmp_path / "test_rgba.png")
    img = Image.new("RGBA", (800, 400), (255, 100, 50, 200))
    img.save(img_path)
    return img_path


def test_static_sticker_conversion(sample_image, tmp_path):
    output_webp = str(tmp_path / "sticker_static.webp")
    options = EncodeOptions()

    messages = []
    def callback(progress, msg):
        messages.append((progress, msg))

    success = StickerEncoder.convert(sample_image, output_webp, options, progress_callback=callback)
    assert success is True
    assert os.path.exists(output_webp)

    # File size <= 512KB
    assert os.path.getsize(output_webp) <= 512 * 1024

    # Verify lossless mode was applied
    assert any("纯无损" in msg for _, msg in messages)

    info = MediaAnalyzer.analyze(output_webp)
    # One side must be 512px, the other <= 512px
    assert max(info.width, info.height) == 512
    assert min(info.width, info.height) <= 512
