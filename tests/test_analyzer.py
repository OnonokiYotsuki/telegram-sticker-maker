from core.analyzer import _parse_frame_rate, pix_fmt_has_alpha, stream_has_alpha


def test_pix_fmt_has_alpha():
    assert pix_fmt_has_alpha("yuva420p") is True
    assert pix_fmt_has_alpha("rgba") is True
    assert pix_fmt_has_alpha("gbrap") is True
    assert pix_fmt_has_alpha("gbrp") is False
    assert pix_fmt_has_alpha("yuv420p") is False
    assert pix_fmt_has_alpha("") is False


def test_stream_has_alpha_from_vp9_tag():
    assert stream_has_alpha({"pix_fmt": "yuv420p", "tags": {"alpha_mode": "1"}}) is True
    assert stream_has_alpha({"pix_fmt": "yuv420p", "tags": {"ALPHA_MODE": "1"}}) is True
    assert stream_has_alpha({"pix_fmt": "yuv420p", "tags": {"alpha_mode": "0"}}) is False
    assert stream_has_alpha({"pix_fmt": "yuva420p"}) is True


def test_parse_frame_rate():
    assert _parse_frame_rate("30000/1001") == 29.97
    assert _parse_frame_rate("24/1") == 24.0
    assert _parse_frame_rate("30") == 30.0
    assert _parse_frame_rate("N/A") == 30.0
    assert _parse_frame_rate("12/0") == 30.0
