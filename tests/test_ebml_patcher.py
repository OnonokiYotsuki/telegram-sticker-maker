import os
import subprocess
import pytest
from core.analyzer import MediaAnalyzer
from core.ebml_patcher import EBMLPatcher
from core.encoder import EncodeOptions, StickerEncoder


@pytest.fixture
def sample_video(tmp_path):
    # Generate a 5-second synthetic test video with animation and colors
    video_path = str(tmp_path / "test_5s.mp4")
    cmd = [
        "ffmpeg",
        "-y",
        "-f", "lavfi",
        "-i", "testsrc=duration=5:size=320x240:rate=30",
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        video_path,
    ]
    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    assert res.returncode == 0
    return video_path


def test_ebml_patcher_and_encoder(sample_video, tmp_path):
    output_webm = str(tmp_path / "sticker_output.webm")
    options = EncodeOptions(
        preset_style="fast",
        spoof_duration=True,
        crop_to_3s=False,
    )

    success = StickerEncoder.convert(sample_video, output_webm, options)
    assert success is True
    assert os.path.exists(output_webm)

    # 1. Check file size <= 256 KB
    size_bytes = os.path.getsize(output_webm)
    assert size_bytes <= 256 * 1024, f"File size {size_bytes} exceeds 256KB"

    # 2. Check spoofed duration via EBMLPatcher
    dur = EBMLPatcher.get_duration(output_webm)
    assert dur is not None
    assert abs(dur - 2.99) < 0.05, f"Expected duration ~2.99s, got {dur}"

    # 3. Check with MediaAnalyzer / ffprobe
    info = MediaAnalyzer.analyze(output_webm)
    assert max(info.width, info.height) == 512
    assert info.width % 2 == 0
    assert info.height % 2 == 0
    assert info.audio_codec is None
