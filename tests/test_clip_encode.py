import os
import subprocess
import pytest
from core.analyzer import MediaAnalyzer
from core.encoder import EncodeOptions, StickerEncoder


@pytest.fixture
def sample_video(tmp_path):
    # 10-second test video
    vpath = str(tmp_path / "sample_10s.mp4")
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi",
        "-i", "testsrc=duration=10:size=640x360:rate=24",
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        vpath
    ]
    subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
    return vpath


def test_encode_video_clip(sample_video, tmp_path):
    # Clip 2.5 seconds from 3.0s to 5.5s
    out_clip = str(tmp_path / "clip_3_to_5_5.webm")
    options = EncodeOptions(
        preset_style="fast",
        start_time=3.0,
        end_time=5.5,
    )

    success = StickerEncoder.convert(sample_video, out_clip, options)
    assert success is True
    assert os.path.exists(out_clip)

    size = os.path.getsize(out_clip)
    assert 0 < size <= 256 * 1024

    info = MediaAnalyzer.analyze(out_clip)
    # Duration should be approximately 2.5 seconds
    assert 2.2 <= info.duration <= 2.8


def test_encode_multiple_clips_from_same_video(sample_video, tmp_path):
    # Clip 1: 1.0 to 3.0
    out1 = str(tmp_path / "clip1.webm")
    opt1 = EncodeOptions(preset_style="fast", start_time=1.0, end_time=3.0)
    res1 = StickerEncoder.convert(sample_video, out1, opt1)
    assert res1 is True
    assert os.path.exists(out1)

    # Clip 2: 6.0 to 8.5
    out2 = str(tmp_path / "clip2.webm")
    opt2 = EncodeOptions(preset_style="fast", start_time=6.0, end_time=8.5)
    res2 = StickerEncoder.convert(sample_video, out2, opt2)
    assert res2 is True
    assert os.path.exists(out2)

    # Both clips exist independently and are within 256KB
    assert os.path.getsize(out1) <= 256 * 1024
    assert os.path.getsize(out2) <= 256 * 1024
