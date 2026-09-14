from core.analyzer import _parse_frame_rate, pix_fmt_has_alpha


def test_pix_fmt_has_alpha():
    assert pix_fmt_has_alpha("yuva420p") is True
    assert pix_fmt_has_alpha("rgba") is True
    assert pix_fmt_has_alpha("gbrap") is True
    assert pix_fmt_has_alpha("gbrp") is False
    assert pix_fmt_has_alpha("yuv420p") is False
    assert pix_fmt_has_alpha("") is False


def test_parse_frame_rate():
    assert _parse_frame_rate("30000/1001") == 29.97
    assert _parse_frame_rate("24/1") == 24.0
    assert _parse_frame_rate("30") == 30.0
    assert _parse_frame_rate("N/A") == 30.0
    assert _parse_frame_rate("12/0") == 30.0
