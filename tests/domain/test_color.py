"""Pure domain tests for circadian color temperature calculations.

These tests verify the pure mathematical functions in domain/color.py
without any Home Assistant dependencies or side effects.
"""

from __future__ import annotations

import pytest

from custom_components.daynight_lighting.domain.color import (
    calculate_kelvin_from_elevation,
    clamp_kelvin,
    mix_kelvin,
    DEFAULT_CIRCADIAN_ELEVATION_MIN,
    DEFAULT_CIRCADIAN_ELEVATION_MAX,
)
from custom_components.daynight_lighting.domain.models import CircadianResult


class TestCalculateKelvinFromElevation:
    """Tests for calculate_kelvin_from_elevation function."""

    def test_none_elevation_returns_min_kelvin_fallback(self):
        """When elevation is None, return min_kelvin as fallback."""
        result = calculate_kelvin_from_elevation(
            elevation=None,
            min_kelvin=2700,
            max_kelvin=6500,
        )

        assert isinstance(result, CircadianResult)
        assert result.kelvin == 2700
        assert result.sun_elevation is None
        assert result.source == "min_fallback"

    def test_elevation_below_min_returns_min_kelvin(self):
        """Elevation below minimum returns min_kelvin."""
        result = calculate_kelvin_from_elevation(
            elevation=-30.0,  # Below default min of -20°
            min_kelvin=2700,
            max_kelvin=6500,
        )

        assert result.kelvin == 2700
        assert result.sun_elevation == -30.0
        assert result.source == "min_fallback"

    def test_elevation_above_max_returns_max_kelvin(self):
        """Elevation above maximum returns max_kelvin."""
        result = calculate_kelvin_from_elevation(
            elevation=70.0,  # Above default max of 60°
            min_kelvin=2700,
            max_kelvin=6500,
        )

        assert result.kelvin == 6500
        assert result.sun_elevation == 70.0
        assert result.source == "max_fallback"

    def test_elevation_at_min_boundary(self):
        """Elevation exactly at minimum returns min_kelvin."""
        result = calculate_kelvin_from_elevation(
            elevation=DEFAULT_CIRCADIAN_ELEVATION_MIN,  # -20°
            min_kelvin=2700,
            max_kelvin=6500,
        )

        assert result.kelvin == 2700
        assert result.source == "min_fallback"

    def test_elevation_at_max_boundary(self):
        """Elevation exactly at maximum returns max_kelvin."""
        result = calculate_kelvin_from_elevation(
            elevation=DEFAULT_CIRCADIAN_ELEVATION_MAX,  # 60°
            min_kelvin=2700,
            max_kelvin=6500,
        )

        assert result.kelvin == 6500
        assert result.source == "max_fallback"

    def test_linear_interpolation_mid_range(self):
        """Elevation between min and max is linearly interpolated."""
        # Test at midpoint: (30 - (-20)) / (60 - (-20)) = 50/80 = 0.625
        # Kelvin: 2700 + (6500-2700)*0.625 = 2700 + 3800*0.625 = 2700 + 2375 = 5075
        result = calculate_kelvin_from_elevation(
            elevation=30.0,  # Midpoint between -20 and 60
            min_kelvin=2700,
            max_kelvin=6500,
        )

        assert result.kelvin == 5075
        assert result.sun_elevation == 30.0
        assert result.source == "circadian"

    def test_interpolation_at_horizon(self):
        """Sun at horizon (0°) interpolates correctly."""
        # 0° is 20/80 = 0.25 of the way from -20 to 60
        # Kelvin: 2700 + (6500-2700)*0.25 = 2700 + 3800*0.25 = 2700 + 950 = 3650
        result = calculate_kelvin_from_elevation(
            elevation=0.0,
            min_kelvin=2700,
            max_kelvin=6500,
        )

        assert result.kelvin == 3650
        assert result.source == "circadian"

    def test_custom_elevation_range(self):
        """Custom elevation min/max values are used."""
        result = calculate_kelvin_from_elevation(
            elevation=15.0,
            min_kelvin=2200,
            max_kelvin=5000,
            elevation_min=0.0,
            elevation_max=45.0,
        )

        # (15-0)/(45-0) = 15/45 = 0.333...
        # 2200 + (5000-2200)*0.333... = 2200 + 2800*0.333... = 2200 + 933 = 3133
        assert result.kelvin == 3133
        assert result.source == "circadian"

    def test_reversed_elevation_range_raises_value_error(self):
        """When elevation_min > elevation_max, function raises ValueError."""
        with pytest.raises(ValueError, match="elevation_min.*must be < elevation_max"):
            calculate_kelvin_from_elevation(
                elevation=30.0,
                min_kelvin=2700,
                max_kelvin=6500,
                elevation_min=60.0,   # Intentionally reversed
                elevation_max=-20.0,  # Intentionally reversed
            )

    def test_negative_kelvin_range(self):
        """Function works with unusual Kelvin ranges (though not realistic)."""
        result = calculate_kelvin_from_elevation(
            elevation=20.0,
            min_kelvin=1000,
            max_kelvin=2000,
        )

        # (20-(-20))/(60-(-20)) = 40/80 = 0.5
        # 1000 + (2000-1000)*0.5 = 1000 + 1000*0.5 = 1500
        assert result.kelvin == 1500
        assert result.source == "circadian"

    def test_rounding_to_nearest_integer(self):
        """Kelvin values are rounded to nearest integer."""
        # Elevation = 10°: (10-(-20))/(60-(-20)) = 30/80 = 0.375
        # 2700 + (6500-2700)*0.375 = 2700 + 3800*0.375 = 2700 + 1425 = 4125
        result = calculate_kelvin_from_elevation(
            elevation=10.0,
            min_kelvin=2700,
            max_kelvin=6500,
        )

        assert result.kelvin == 4125

    def test_small_elevation_range(self):
        """Works with very small elevation range."""
        result = calculate_kelvin_from_elevation(
            elevation=0.5,
            min_kelvin=2700,
            max_kelvin=3000,
            elevation_min=0.0,
            elevation_max=1.0,
        )

        # (0.5-0)/(1-0) = 0.5/1 = 0.5
        # 2700 + (3000-2700)*0.5 = 2700 + 300*0.5 = 2850
        assert result.kelvin == 2850
        assert result.source == "circadian"


class TestClampKelvin:
    """Tests for clamp_kelvin utility function."""

    def test_value_within_range_unchanged(self):
        """Value within [min, max] is returned unchanged."""
        assert clamp_kelvin(4000, 2700, 6500) == 4000
        assert clamp_kelvin(2700, 2700, 6500) == 2700  # At min
        assert clamp_kelvin(6500, 2700, 6500) == 6500  # At max

    def test_value_below_min_clamped(self):
        """Value below minimum is clamped to min."""
        assert clamp_kelvin(2000, 2700, 6500) == 2700
        assert clamp_kelvin(1000, 2700, 6500) == 2700
        assert clamp_kelvin(-1000, 2700, 6500) == 2700

    def test_value_above_max_clamped(self):
        """Value above maximum is clamped to max."""
        assert clamp_kelvin(7000, 2700, 6500) == 6500
        assert clamp_kelvin(10000, 2700, 6500) == 6500

    def test_custom_range(self):
        """Custom min/max values are respected."""
        assert clamp_kelvin(3500, 3000, 4000) == 3500
        assert clamp_kelvin(2500, 3000, 4000) == 3000  # Below min
        assert clamp_kelvin(4500, 3000, 4000) == 4000  # Above max

    def test_reversed_range_still_works(self):
        """When min > max, function still works (uses max/min)."""
        # clamp_kelvin uses max(min_kelvin, min(max_kelvin, kelvin))
        # So with min=6500, max=2700: max(6500, min(2700, 4000)) = max(6500, 2700) = 6500
        assert clamp_kelvin(4000, 6500, 2700) == 6500

    def test_same_min_max(self):
        """When min == max, always returns that value."""
        assert clamp_kelvin(4000, 3000, 3000) == 3000
        assert clamp_kelvin(2000, 3000, 3000) == 3000
        assert clamp_kelvin(5000, 3000, 3000) == 3000


class TestMixKelvin:
    """Tests for mix_kelvin function."""

    def test_ratio_zero_returns_first_kelvin(self):
        """Ratio 0.0 returns first Kelvin value."""
        assert mix_kelvin(2700, 6500, 0.0) == 2700
        assert mix_kelvin(3000, 4000, 0.0) == 3000

    def test_ratio_one_returns_second_kelvin(self):
        """Ratio 1.0 returns second Kelvin value."""
        assert mix_kelvin(2700, 6500, 1.0) == 6500
        assert mix_kelvin(3000, 4000, 1.0) == 4000

    def test_ratio_half_returns_midpoint(self):
        """Ratio 0.5 returns midpoint."""
        assert mix_kelvin(2700, 6500, 0.5) == 4600  # (2700+6500)/2 = 4600
        assert mix_kelvin(3000, 5000, 0.5) == 4000  # (3000+5000)/2 = 4000

    def test_partial_ratio(self):
        """Partial ratios interpolate correctly."""
        # 2700 + (6500-2700)*0.25 = 2700 + 3800*0.25 = 2700 + 950 = 3650
        assert mix_kelvin(2700, 6500, 0.25) == 3650

        # 2700 + (6500-2700)*0.75 = 2700 + 3800*0.75 = 2700 + 2850 = 5550
        assert mix_kelvin(2700, 6500, 0.75) == 5550

    def test_ratio_clamped_below_zero(self):
        """Ratio < 0.0 is clamped to 0.0."""
        assert mix_kelvin(2700, 6500, -0.5) == 2700
        assert mix_kelvin(2700, 6500, -1.0) == 2700

    def test_ratio_clamped_above_one(self):
        """Ratio > 1.0 is clamped to 1.0."""
        assert mix_kelvin(2700, 6500, 1.5) == 6500
        assert mix_kelvin(2700, 6500, 2.0) == 6500

    def test_rounding_to_nearest_integer(self):
        """Mixed values are rounded to nearest integer."""
        # 2700 + (6500-2700)*0.333... = 2700 + 3800*0.333... = 2700 + 1266.66... = 3966.66...
        assert mix_kelvin(2700, 6500, 1/3) == 3967

        # 2700 + (6500-2700)*0.666... = 2700 + 3800*0.666... = 2700 + 2533.33... = 5233.33...
        assert mix_kelvin(2700, 6500, 2/3) == 5233

    def test_mixing_with_same_values(self):
        """Mixing same values returns that value regardless of ratio."""
        assert mix_kelvin(3000, 3000, 0.0) == 3000
        assert mix_kelvin(3000, 3000, 0.5) == 3000
        assert mix_kelvin(3000, 3000, 1.0) == 3000
        assert mix_kelvin(3000, 3000, 0.3) == 3000

    def test_mixing_extreme_values(self):
        """Mixing works with extreme Kelvin values."""
        assert mix_kelvin(1000, 10000, 0.5) == 5500
        assert mix_kelvin(1000, 2000, 0.3) == 1300  # 1000 + 1000*0.3 = 1300

    def test_decreasing_kelvin_range(self):
        """Mixing works when kelvin2 < kelvin1 (decreasing range)."""
        # 6500 + (2700-6500)*0.5 = 6500 - 3800*0.5 = 6500 - 1900 = 4600
        assert mix_kelvin(6500, 2700, 0.5) == 4600

        # 5000 + (3000-5000)*0.25 = 5000 - 2000*0.25 = 5000 - 500 = 4500
        assert mix_kelvin(5000, 3000, 0.25) == 4500


class TestCalculateKelvinFromElevationValidation:
    """Tests for calculate_kelvin_from_elevation input validation."""

    def test_reversed_kelvin_raises(self):
        """min_kelvin >= max_kelvin raises ValueError."""
        with pytest.raises(ValueError, match="min_kelvin.*must be < max_kelvin"):
            calculate_kelvin_from_elevation(
                elevation=30.0,
                min_kelvin=6500,
                max_kelvin=2700,
            )

    def test_equal_kelvin_raises(self):
        """min_kelvin == max_kelvin raises ValueError."""
        with pytest.raises(ValueError, match="min_kelvin.*must be < max_kelvin"):
            calculate_kelvin_from_elevation(
                elevation=30.0,
                min_kelvin=4000,
                max_kelvin=4000,
            )

    def test_kelvin_below_1000_raises(self):
        """min_kelvin < 1000 raises ValueError."""
        with pytest.raises(ValueError, match="min_kelvin.*must be >= 1000K"):
            calculate_kelvin_from_elevation(
                elevation=30.0,
                min_kelvin=500,
                max_kelvin=6500,
            )

    def test_reversed_elevation_range_raises(self):
        """elevation_min >= elevation_max raises ValueError."""
        with pytest.raises(ValueError, match="elevation_min.*must be < elevation_max"):
            calculate_kelvin_from_elevation(
                elevation=30.0,
                min_kelvin=2700,
                max_kelvin=6500,
                elevation_min=60.0,
                elevation_max=-20.0,
            )