"""Tests for the pure brightness formulas the mode handlers apply.

The values are pinned on purpose: day brightness rounds, the weather modifier
and the ramps truncate. A formula that "improves" either would shift lamps
by a percent and make our own commands look like external control.
"""

from __future__ import annotations

import pytest

from custom_components.daynight_lighting.domain.brightness import (
    apply_weather_modifier,
    brightness_to_pct,
    lux_to_brightness_pct,
    ramp_value,
)
from custom_components.daynight_lighting.handlers import base as handler_base


class TestBrightnessToPct:
    """Convert HA brightness (0-255) to percent (0-100)."""

    def test_none_stays_none(self):
        assert brightness_to_pct(None) is None

    def test_zero(self):
        assert brightness_to_pct(0) == 0

    def test_full(self):
        assert brightness_to_pct(255) == 100

    def test_mid(self):
        assert brightness_to_pct(128) == 50

    def test_clamped_low(self):
        assert brightness_to_pct(-10) == 0

    def test_clamped_high(self):
        assert brightness_to_pct(300) == 100

    def test_handlers_use_the_domain_formula(self):
        assert handler_base.brightness_to_pct is brightness_to_pct


class TestLuxToBrightnessPct:
    """Day brightness from LUX: dark room bright lamps, bright room dim lamps."""

    @pytest.mark.parametrize(
        ("lux", "expected"),
        [
            (0, 100),
            (10, 100),  # at lux_on: max
            (32.5, 78),  # 77.5 rounds half to even
            (55, 55),
            (99.9, 10),
            (100, 10),  # at lux_off: min
            (5000, 10),
        ],
    )
    def test_linear_between_thresholds(self, lux, expected):
        assert lux_to_brightness_pct(lux, 10, 100, 10, 100) == expected

    def test_bright_room_with_zero_min_is_off(self):
        assert lux_to_brightness_pct(100, 10, 100, 0, 100) is None
        assert lux_to_brightness_pct(250, 10, 100, 0, 100) is None

    def test_just_below_lux_off_with_zero_min_stays_on(self):
        assert lux_to_brightness_pct(99, 10, 100, 0, 100) == 1

    def test_result_is_clamped_to_percent(self):
        assert lux_to_brightness_pct(50, 10, 100, 0, 100) == 56

    def test_handlers_use_the_domain_formula(self):
        assert handler_base.lux_to_brightness_pct is lux_to_brightness_pct


class TestApplyWeatherModifier:
    """Weather scales the day brightness within the configured min and max."""

    @pytest.mark.parametrize(
        ("pct", "modifier", "expected"),
        [
            (50, 1.0, 50),
            (50, 1.2, 60),
            (55, 0.85, 46),  # 46.75 truncates
            (33, 1.3, 42),  # 42.9 truncates
            (80, 0.7, 56),
        ],
    )
    def test_truncates(self, pct, modifier, expected):
        assert apply_weather_modifier(pct, modifier, 0, 100) == expected

    def test_clamped_to_day_max(self):
        assert apply_weather_modifier(90, 1.3, 10, 100) == 100
        assert apply_weather_modifier(70, 1.3, 10, 80) == 80

    def test_clamped_to_day_min(self):
        assert apply_weather_modifier(20, 0.7, 20, 100) == 20


class TestRampValue:
    """Sleep and wake-up ramps: linear, truncating, unclamped."""

    @pytest.mark.parametrize(
        ("start", "end", "progress", "expected"),
        [
            (80, 20, 0.0, 80),
            (80, 20, 0.5, 50),
            (80, 20, 1.0, 20),
            (80, 20, 0.33, 60),  # 60.2 truncates
            (1, 100, 0.5, 50),  # 50.5 truncates
            (1, 100, 0.999, 99),
            (2700, 2200, 0.25, 2575),
        ],
    )
    def test_linear_and_truncating(self, start, end, progress, expected):
        assert ramp_value(start, end, progress) == expected

    def test_matches_the_expression_it_replaced(self):
        for start, end in [(80, 20), (1, 100), (100, 1), (2700, 2200)]:
            for step in range(101):
                progress = step / 100
                assert ramp_value(start, end, progress) == int(
                    start + (end - start) * progress
                )
