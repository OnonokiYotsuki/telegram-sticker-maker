import os
import subprocess
import pytest
from core.analyzer import MediaAnalyzer
from core.ebml_patcher import EBMLPatcher
from core.encoder import EncodeOptions, StickerEncoder


@pytest.fixture
def long_video(tmp_path):
    # 7-second test video
    vpath = str(tmp_path / "long_7s.mp4")
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi",
        "-i", "testsrc=duration=7:size=640x360:rate=30",
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        vpath
    ]
    subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
    return vpath


def test_duration_spoofing_long_video(long_video, tmp_path):
    output_path = str(tmp_path / "spoofed_7s.webm")
    options = EncodeOptions(
        preset_style="anime",
        spoof_duration=True,
        optimize_fps=True,
        crop_to_3s=False
    )

    success = StickerEncoder.convert(long_video, output_path, options)
    assert success is True
    assert os.path.exists(output_path)

    # Size check
    size = os.path.getsize(output_path)
    assert size <= 256 * 1024, f"Size {size} exceeded 256KB"

    # EBML duration check: should be ~2.99s
    patched_dur = EBMLPatcher.get_duration(output_path)
    assert patched_dur is not None
    assert abs(patched_dur - 2.99) < 0.05, f"Expected 2.99s, got {patched_dur}"


def test_cinema_preset(long_video, tmp_path):
    output_path = str(tmp_path / "cinema_preset.webm")
    options = EncodeOptions(
        preset_style="cinema",
        spoof_duration=True,
        crop_to_3s=False
    )

    success = StickerEncoder.convert(long_video, output_path, options)
    assert success is True
    assert os.path.getsize(output_path) <= 256 * 1024
