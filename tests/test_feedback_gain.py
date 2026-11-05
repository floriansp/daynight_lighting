"""Physical plausibility of self-induced brightness oscillation."""

import pytest

from custom_components.daynight_lighting.domain.brightness import feedback_gain_bound


@pytest.mark.parametrize("raw,brightness,calibration,expected", [
    (47, 55, None, 47 / 55 * 80 / 130),
    (0.57, 78, None, 0.57 / 78 * 80 / 130),
    (50, 25, 40, 0.4 * 80 / 130),
    (None, 25, None, None),
    (50, 0, 40, None),
    (50, None, None, None),
])
def test_feedback_gain_bound(raw, brightness, calibration, expected):
    """Calibration is exact; without it nonnegative ambient gives an upper bound."""
    result = feedback_gain_bound(raw, brightness, 10, 140, 0, 80, calibration)
    if expected is None:
        assert result is None
    else:
        assert result == pytest.approx(expected)


@pytest.mark.parametrize("lux_off", [10, 5])
def test_feedback_gain_unknown_for_invalid_lux_interval(lux_off):
    """A zero or inverted curve interval cannot provide a gain bound."""
    assert feedback_gain_bound(50, 25, 10, lux_off, 0, 80) is None
