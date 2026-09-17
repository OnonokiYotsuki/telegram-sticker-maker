import os
from PIL import Image

from core.crop_shape import (
    apply_crop_radius,
    build_radius_mask_filter,
    normalize_crop_radius,
    radius_needs_alpha,
)
from core.encode_plan import build_vf, plan_video
from core.encoder import EncodeOptions, StickerEncoder
from core.analyzer import MediaInfo


def _info(**kwargs) -> MediaInfo:
    defaults = dict(
        file_path="clip.mp4",
        file_name="clip.mp4",
        file_size=1_000_000,
        is_video=True,
        width=1080,
        height=1080,
        duration=3.0,
        fps=24.0,
        has_alpha=False,
        format_name="mp4",
        video_codec="h264",
    )
    defaults.update(kwargs)
    return MediaInfo(**defaults)


def test_normalize_crop_radius():
    assert normalize_crop_radius(None) == 0.0
    assert normalize_crop_radius("") == 0.0
    assert normalize_crop_radius("1") == 1.0
    assert normalize_crop_radius(1.5) == 1.0
    assert normalize_crop_radius(-0.2) == 0.0
    assert normalize_crop_radius("nope") == 0.0


def test_crop_radius_label():
    from core.crop_shape import crop_radius_label

    assert crop_radius_label(0) == "直角"
    assert crop_radius_label(1) == "圆形"
    assert crop_radius_label(0.5) == "圆角 50%"


def test_radius_needs_alpha():
    assert radius_needs_alpha(0) is False
    assert radius_needs_alpha(0.2) is True
    assert radius_needs_alpha(1) is True


def test_build_radius_mask_filter_escapes_commas():
    vf = build_radius_mask_filter(1.0)
    assert vf.startswith("format=rgba,geq=")
    assert "\\," in vf
    assert build_radius_mask_filter(0) == ""


def test_plan_video_full_radius_enables_alpha():
    opts = EncodeOptions(crop=(0, 0, 1080, 1080), crop_radius=1.0)
    plan = plan_video(_info(), opts)
    assert plan.pix_fmt == "yuva420p"
    assert plan.auto_alt_ref == 0
    assert "geq=" in plan.vf
    assert "crop=1080:1080:0:0" in plan.vf


def test_build_vf_keeps_rect_without_geq():
    vf = build_vf(
        is_emoji=False,
        preset_style="fast",
        fps=24,
        source_fps=24,
        crop=(10, 10, 500, 500),
        crop_radius=0,
    )
    assert "geq=" not in vf
    assert "crop=500:500:10:10" in vf


def test_apply_crop_radius_full_circle_corners_transparent():
    img = Image.new("RGBA", (100, 100), (255, 0, 0, 255))
    out = apply_crop_radius(img, 1.0)
    assert out.getpixel((0, 0))[3] == 0
    assert out.getpixel((99, 0))[3] == 0
    assert out.getpixel((50, 50))[3] == 255


def test_apply_crop_radius_zero_keeps_opaque():
    img = Image.new("RGBA", (40, 40), (0, 255, 0, 255))
    out = apply_crop_radius(img, 0)
    assert out.getpixel((0, 0))[3] == 255
    assert out.getpixel((20, 20))[3] == 255


def test_apply_crop_radius_partial_round():
    img = Image.new("RGBA", (80, 80), (0, 0, 255, 255))
    out = apply_crop_radius(img, 0.4)
    assert out.getpixel((0, 0))[3] == 0
    assert out.getpixel((40, 40))[3] == 255
    assert out.getpixel((40, 2))[3] == 255


def test_static_circle_sticker_has_transparent_corners(tmp_path):
    src = tmp_path / "solid.png"
    Image.new("RGB", (400, 400), (220, 40, 40)).save(src)
    out = str(tmp_path / "circle.webp")
    ok = StickerEncoder.convert(
        str(src),
        out,
        EncodeOptions(crop=(0, 0, 400, 400), crop_radius=1.0),
    )
    assert ok is True
    assert os.path.exists(out)
    result = Image.open(out).convert("RGBA")
    assert result.getpixel((0, 0))[3] < 20
    cx, cy = result.size[0] // 2, result.size[1] // 2
    assert result.getpixel((cx, cy))[3] > 200
