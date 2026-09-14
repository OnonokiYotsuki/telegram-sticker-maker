import pytest
from core.encoder import StickerEncoder
from core.time_format import parse_time_str, format_time_str


def test_parse_time_str_valid():
    assert parse_time_str("00:14:23.500") == pytest.approx(863.5)
    assert parse_time_str("14:23.5") == pytest.approx(863.5)
    assert parse_time_str("01:00:00") == pytest.approx(3600.0)
    assert parse_time_str("23.5") == pytest.approx(23.5)
    assert parse_time_str("2.5s") == pytest.approx(2.5)
    assert parse_time_str("863") == pytest.approx(863.0)
    assert parse_time_str("0") == pytest.approx(0.0)
    assert parse_time_str(" 00:02.500 ") == pytest.approx(2.5)


def test_parse_time_str_invalid():
    assert parse_time_str("") is None
    assert parse_time_str("   ") is None
    assert parse_time_str("invalid") is None
    assert parse_time_str("-5") is None
    assert parse_time_str("01:99:99") is None
    assert parse_time_str("01:23:45:67") is None


def test_format_time_str():
    assert format_time_str(863.5) == "14:23.500"
    assert format_time_str(3661.25) == "01:01:01.250"
    assert format_time_str(2.5) == "00:02.500"
    assert format_time_str(0.0) == "00:00.000"


def test_seek_args():
    # None or zero start time
    pre, post = StickerEncoder._seek_args(None, 2.5)
    assert pre == []
    assert post == ["-t", "2.500"]

    # Short start time <= 10s: fine seek only
    pre, post = StickerEncoder._seek_args(3.5, 2.0)
    assert pre == []
    assert post == ["-ss", "3.500", "-t", "2.000"]

    # Long start time > 10s: two-stage seek (pre_seek jump + post_seek fine decode)
    pre, post = StickerEncoder._seek_args(863.5, 2.5)
    assert pre == ["-ss", "859.500"]
    assert post == ["-ss", "4.000", "-t", "2.500"]
