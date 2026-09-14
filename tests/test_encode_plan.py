from core.analyzer import MediaInfo
from core.encode_plan import (
    EMERGENCY_FPS,
    STICKER_PAYLOAD_BYTES,
    choose_bitrate_kbps,
    output_dims,
    plan_video,
)
from core.encoder import EncodeOptions


def _info(**kwargs) -> MediaInfo:
    defaults = dict(
        file_path="clip.mp4",
        file_name="clip.mp4",
        file_size=1_000_000,
        is_video=True,
        width=1080,
        height=1920,
        duration=3.0,
        fps=24.0,
        has_alpha=False,
        format_name="mp4",
        video_codec="h264",
    )
    defaults.update(kwargs)
    return MediaInfo(**defaults)


def test_output_dims_portrait_and_landscape():
    assert output_dims(1080, 1920, 512) == (288, 512)
    assert output_dims(1920, 1080, 512) == (512, 288)
    assert output_dims(512, 512, 512) == (512, 512)
    assert output_dims(500, 300, 512) == (512, 304)


def test_short_square_keeps_24_and_uses_cq():
    plan = plan_video(_info(width=512, height=512, duration=2.0, fps=24.0), EncodeOptions())
    assert plan.fps == 24
    assert plan.crf is not None
    assert plan.two_pass is True
    assert plan.bitrate_kbps >= 800


def test_seven_second_clip_stays_near_source_fps():
    plan = plan_video(
        _info(width=640, height=360, duration=7.0, fps=30.0),
        EncodeOptions(optimize_fps=True),
    )
    assert plan.fps == 30
    assert plan.crf is None
    assert "fps=" not in plan.vf


def test_tak_like_high_motion_drops_to_15_not_12():
    plan = plan_video(
        _info(width=1080, height=1920, duration=17.5, fps=24.0),
        EncodeOptions(optimize_fps=True),
        motion_score=0.018,
    )
    assert plan.fps == 15
    assert plan.crf is None
    assert plan.two_pass is True
    assert 100 <= plan.bitrate_kbps <= 130
    assert "fps=15" in plan.vf


def test_tak_like_low_motion_keeps_24():
    plan = plan_video(
        _info(width=1080, height=1920, duration=17.5, fps=24.0),
        EncodeOptions(optimize_fps=True),
        motion_score=0.002,
    )
    assert plan.fps == 24
    assert "fps=15" not in plan.vf
    assert "fps=12" not in plan.vf


def test_square_long_high_motion_may_use_emergency_fps():
    plan = plan_video(
        _info(width=512, height=512, duration=17.5, fps=24.0),
        EncodeOptions(optimize_fps=True),
        motion_score=0.02,
    )
    assert plan.fps in (12, 15)
    assert plan.fps <= 15


def test_gif_10fps_is_never_upsampled():
    plan = plan_video(
        _info(width=100, height=100, duration=1.0, fps=10.0, format_name="gif"),
        EncodeOptions(),
    )
    assert plan.fps == 10
    assert "fps=" not in plan.vf or "fps=10" in plan.vf


def test_emoji_keeps_source_fps_and_60kb_budget():
    plan = plan_video(
        _info(width=150, height=100, duration=2.0, fps=10.0),
        EncodeOptions(is_custom_emoji=True),
    )
    assert plan.fps == 10
    assert plan.out_w == 100 and plan.out_h == 100
    assert plan.payload_bytes == 60 * 1024
    assert plan.bitrate_kbps == choose_bitrate_kbps(plan.payload_bytes, 2.0)


def test_optimize_fps_off_keeps_source():
    plan = plan_video(
        _info(width=1080, height=1920, duration=17.5, fps=24.0),
        EncodeOptions(optimize_fps=False),
        motion_score=0.02,
    )
    assert plan.fps == 24


def test_long_clip_bitrate_is_not_floored_at_80k():
    plan = plan_video(
        _info(width=1080, height=1920, duration=40.0, fps=24.0),
        EncodeOptions(),
        motion_score=0.02,
    )
    expected = choose_bitrate_kbps(STICKER_PAYLOAD_BYTES, 40.0)
    assert expected < 80
    assert plan.bitrate_kbps == expected


def test_fast_preset_is_single_pass():
    plan = plan_video(_info(duration=3.0, fps=24.0), EncodeOptions(preset_style="fast"))
    assert plan.two_pass is False
    assert plan.cpu_used_pass2 >= 4


def test_anime_filter_has_unsharp_cinema_has_denoise():
    anime = plan_video(_info(), EncodeOptions(preset_style="anime"))
    cinema = plan_video(_info(), EncodeOptions(preset_style="cinema"))
    assert "unsharp" in anime.vf
    assert "hqdn3d" in cinema.vf
    assert "unsharp" not in cinema.vf


def test_alpha_disables_alt_ref():
    plan = plan_video(_info(has_alpha=True), EncodeOptions())
    assert plan.pix_fmt == "yuva420p"
    assert plan.auto_alt_ref == 0


def test_emergency_fps_constant():
    assert EMERGENCY_FPS == 12


def test_crop_in_plan_video():
    info = _info(width=1920, height=1080, duration=3.0, fps=24.0)
    opts = EncodeOptions(crop=(420, 0, 1080, 1080))
    plan = plan_video(info, opts)
    assert plan.out_w == 512
    assert plan.out_h == 512
    assert "crop=1080:1080:420:0" in plan.vf

