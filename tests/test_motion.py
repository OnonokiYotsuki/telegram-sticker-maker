from core.encoder import mean_luma_sad


def test_mean_luma_sad_identical_is_zero():
    frame = bytes([40] * (160 * 90))
    assert mean_luma_sad(frame, frame, 160, 90) == 0.0


def test_mean_luma_sad_full_swing():
    black = bytes([0] * (8 * 8))
    white = bytes([255] * (8 * 8))
    assert mean_luma_sad(black, white, 8, 8) == 1.0
