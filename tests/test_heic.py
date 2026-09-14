import os
import pytest
from PIL import Image
import pillow_heif

from core.ai_tagger import AIEmojiTagger
from core.analyzer import MediaAnalyzer
from core.encoder import EncodeOptions, StickerEncoder

# Ensure opener is registered
pillow_heif.register_heif_opener()


@pytest.fixture
def sample_heic(tmp_path):
    heic_path = str(tmp_path / "test_sample.heic")
    img = Image.new("RGBA", (400, 300), (0, 0, 0, 0))
    # Draw a colored square in the center, leaving alpha around
    for x in range(100, 300):
        for y in range(80, 220):
            img.putpixel((x, y), (255, 120, 50, 220))
    img.save(heic_path, format="HEIF")
    return heic_path


def test_heic_media_analyzer(sample_heic):
    info = MediaAnalyzer.analyze(sample_heic)
    assert info.is_video is False
    assert info.width == 400
    assert info.height == 300
    assert info.has_alpha is True
    assert info.duration == 0.0


def test_heic_conversion_sticker(sample_heic, tmp_path):
    output_webp = str(tmp_path / "sticker.webp")
    options = EncodeOptions()

    success = StickerEncoder.convert(sample_heic, output_webp, options)
    assert success is True
    assert os.path.exists(output_webp)
    assert os.path.getsize(output_webp) <= 512 * 1024

    info = MediaAnalyzer.analyze(output_webp)
    assert max(info.width, info.height) == 512
    assert min(info.width, info.height) <= 512
    assert info.has_alpha is True

    # Verify alpha channel was preserved (not lost / blacked out)
    with Image.open(output_webp) as out_img:
        assert out_img.mode == "RGBA"
        alpha_band = out_img.getchannel("A")
        assert alpha_band.getextrema()[0] == 0


def test_heic_conversion_custom_emoji(sample_heic, tmp_path):
    output_webp = str(tmp_path / "custom_emoji.webp")
    options = EncodeOptions(is_custom_emoji=True)

    success = StickerEncoder.convert(sample_heic, output_webp, options)
    assert success is True
    assert os.path.exists(output_webp)
    assert os.path.getsize(output_webp) <= 64 * 1024

    info = MediaAnalyzer.analyze(output_webp)
    assert info.width == 100
    assert info.height == 100
    assert info.has_alpha is True


def test_heic_ai_tagger_frame_extraction(sample_heic):
    b64 = AIEmojiTagger.extract_frame_base64(sample_heic, max_dim=256)
    assert b64 is not None
    assert len(b64) > 50



