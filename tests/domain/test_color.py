"""Pure domain tests for circadian color temperature calculations.

These tests verify the pure mathematical functions in domain/color.py
without any Home Assistant dependencies or side effects.
"""

from __future__ import annotations

import pytest

from custom_components.daynight_lighting.domain.color import (
    calculate_kelvin_from_elevation,
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

    def test_midpoint_elevation_returns_midpoint_kelvin(self):
        """Elevation at midpoint returns midpoint Kelvin."""
        # Midpoint between -20 and 60 is 20
        result = calculate_kelvin_from_elevation(
            elevation=20,
            min_kelvin=2700,
            max_kelvin=6500,
        )
        # t = (20 - (-20)) / (60 - (-20)) = 40/80 = 0.5
        # kelvin = 2700 + (6500-2700) * 0.5 = 2700 + 1900 = 4600
        assert result.kelvin == 4600
        assert result.source == "circadian"

    def test_high_elevation_interpolation(self):
        """High elevation (approaching noon)."""
        result = calculate_kelvin_from_elevation(
            elevation=50,
            min_kelvin=2700,
            max_kelvin=6500,
        )
        # t = (50 - (-20)) / 80 = 70/80 = 0.875
        # kelvin = 2700 + 3800 * 0.875 = 2700 + 3325 = 6025
        assert result.kelvin == 6025

    def test_custom_range_midpoint(self):
        """Custom min/max elevation range works correctly."""
        result = calculate_kelvin_from_elevation(
            elevation=45,  # Midpoint of custom range 30-60
            min_kelvin=2700,
            max_kelvin=6500,
            elevation_min=30,
            elevation_max=60,
        )
        # t = (45 - 30) / (60 - 30) = 15/30 = 0.5
        # kelvin = 2700 + 3800 * 0.5 = 4600
        assert result.kelvin == 4600

    def test_inverted_elevation_range_raises_value_error(self):
        """Inverted elevation min/max raises ValueError."""
        with pytest.raises(ValueError, match="elevation_min.*must be < elevation_max"):
            calculate_kelvin_from_elevation(
                elevation=45,
                min_kelvin=2700,
                max_kelvin=6500,
                elevation_min=60,  # Inverted
                elevation_max=30,  # Inverted
            )

    def test_custom_kelvin_range(self):
        """Custom min/max Kelvin range works correctly."""
        result = calculate_kelvin_from_elevation(
            elevation=20,  # Midpoint
            min_kelvin=2000,  # Very warm
            max_kelvin=4000,  # Neutral
        )
        # kelvin = 2000 + (4000-2000) * 0.5 = 3000
        assert result.kelvin == 3000

    def test_narrow_kelvin_range(self):
        """Narrow Kelvin range for limited hardware support."""
        result = calculate_kelvin_from_elevation(
            elevation=-30,  # Below min
            min_kelvin=2700,
            max_kelvin=3000,  # Only 300K range
        )
        assert result.kelvin == 2700

        result = calculate_kelvin_from_elevation(
            elevation=70,  # Above max
            min_kelvin=2700,
            max_kelvin=3000,
        )
        assert result.kelvin == 3000

    def test_result_contains_sun_elevation(self):
        """Result contains the original sun elevation value."""
        result = calculate_kelvin_from_elevation(
            elevation=25.5,
            min_kelvin=2700,
            max_kelvin=6500,
        )
        assert result.sun_elevation == 25.5


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


class TestDefaultConstants:
    """Tests to verify default constants are reasonable."""

    def test_default_elevation_min_is_negative(self):
        """Default min elevation should be negative (below horizon)."""
        assert DEFAULT_CIRCADIAN_ELEVATION_MIN < 0

    def test_default_elevation_max_is_positive(self):
        """Default max elevation should be positive (above horizon)."""
        assert DEFAULT_CIRCADIAN_ELEVATION_MAX > 0

    def test_default_range_is_valid(self):
        """Default elevation range should have min < max."""
        assert DEFAULT_CIRCADIAN_ELEVATION_MIN < DEFAULT_CIRCADIAN_ELEVATION_MAX
