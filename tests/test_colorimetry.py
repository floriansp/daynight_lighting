"""Tests for the pure colourimetric helpers in domain/colorimetry.py.

These lock in the conversions used by external-control detection to tell our
own circadian white apart from a coloured scene, without a full HA runtime.
"""

from __future__ import annotations

from custom_components.daynight_lighting.domain.colorimetry import (
    COLOR_DISTANCE_THRESHOLD_UV,
    color_attrs_to_xy,
    color_distance_to_kelvin,
    hs_to_rgb,
    kelvin_to_rgb,
    kelvin_to_xy,
    rgb_to_xy,
)


def _approx(a: float, b: float, tol: float = 0.02) -> bool:
    return abs(a - b) <= tol


class TestKelvinToRgb:
    def test_warm_white_is_warm(self):
        r, g, b = kelvin_to_rgb(2700)
        assert r >= g >= b  # warm: red dominant, blue lowest

    def test_cool_white_is_cool(self):
        r, g, b = kelvin_to_rgb(6500)
        assert r >= g >= b  # still monotonic, but much closer together
        assert b > 200

    def test_monotonic_channel_ordering(self):
        # All black-body whites satisfy R >= G >= B.
        for k in (2000, 2700, 3500, 4000, 5000, 6500):
            r, g, b = kelvin_to_rgb(k)
            assert r >= g >= b, f"{k}K: {(r, g, b)}"

    def test_clamped_to_byte_range(self):
        for k in (1000, 2000, 6500, 40000):
            r, g, b = kelvin_to_rgb(k)
            assert all(0 <= c <= 255 for c in (r, g, b))


class TestColorConversions:
    def test_rgb_to_xy_white(self):
        # Neutral grey maps to D65 white point.
        x, y = rgb_to_xy((255, 255, 255))
        assert _approx(x, 0.3127)
        assert _approx(y, 0.3290)

    def test_hs_red_is_saturated(self):
        r, g, b = hs_to_rgb((0.0, 100.0))
        assert r == 255 and g == 0 and b == 0

    def test_color_attrs_prefer_rgb(self):
        attrs = {"rgb_color": (255, 255, 255), "xy_color": (0.5, 0.4)}
        x, y = color_attrs_to_xy(attrs)
        assert _approx(x, 0.3127) and _approx(y, 0.3290)

    def test_color_attrs_fall_back_to_xy(self):
        x, y = color_attrs_to_xy({"xy_color": (0.5, 0.4)})
        assert (x, y) == (0.5, 0.4)

    def test_color_attrs_none_without_color(self):
        assert color_attrs_to_xy({"brightness": 128}) is None


class TestColorDistanceToKelvin:
    def test_own_white_is_zero_distance(self):
        assert color_distance_to_kelvin(
            {"xy_color": kelvin_to_xy(3606)}, 3606
        ) < 1e-9

    def test_own_white_via_rgb_matches(self):
        # The RGB the integration would produce for a kelvin also matches.
        dist = color_distance_to_kelvin({"rgb_color": kelvin_to_rgb(3500)}, 3500)
        assert dist < COLOR_DISTANCE_THRESHOLD_UV

    def test_saturated_scene_is_far(self):
        assert color_distance_to_kelvin(
            {"xy_color": (0.3, 0.6)}, 3500
        ) > COLOR_DISTANCE_THRESHOLD_UV

    def test_clearly_different_white_is_far(self):
        assert color_distance_to_kelvin(
            {"xy_color": kelvin_to_xy(6500)}, 3500
        ) > COLOR_DISTANCE_THRESHOLD_UV

    def test_no_color_returns_none(self):
        assert color_distance_to_kelvin({"brightness": 128}, 3500) is None
