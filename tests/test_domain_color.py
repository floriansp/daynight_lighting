"""Tests for domain/color.py - pure color temperature calculation functions.

These tests verify the circadian color temperature calculations without
any Home Assistant dependencies.
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


# ===================================================================
#  calculate_kelvin_from_elevation
# ===================================================================


class TestCalculateKelvinFromElevation:
    """Tests for calculate_kelvin_from_elevation function."""

    # --- None elevation (no sun data) ---

    def test_none_elevation_returns_min_kelvin(self):
        """When elevation is None, return min_kelvin as fallback."""
        result = calculate_kelvin_from_elevation(
            elevation=None,
            min_kelvin=2700,
            max_kelvin=6500,
        )
        assert result.kelvin == 2700
        assert result.source == "min_fallback"
        assert result.sun_elevation is None

    # --- Below minimum elevation (night) ---

    def test_below_min_elevation_returns_min_kelvin(self):
        """Elevation below min returns min_kelvin (warm, nighttime)."""
        result = calculate_kelvin_from_elevation(
            elevation=-30,  # Below default min of -20
            min_kelvin=2700,
            max_kelvin=6500,
        )
        assert result.kelvin == 2700
        assert result.source == "min_fallback"

    def test_exactly_at_min_elevation_returns_min_kelvin(self):
        """Elevation exactly at min returns min_kelvin."""
        result = calculate_kelvin_from_elevation(
            elevation=-20,  # Exactly at default min
            min_kelvin=2700,
            max_kelvin=6500,
        )
        assert result.kelvin == 2700

    # --- Above maximum elevation (high noon) ---

    def test_above_max_elevation_returns_max_kelvin(self):
        """Elevation above max returns max_kelvin (cool, midday)."""
        result = calculate_kelvin_from_elevation(
            elevation=70,  # Above default max of 60
            min_kelvin=2700,
            max_kelvin=6500,
        )
        assert result.kelvin == 6500
        assert result.source == "max_fallback"

    def test_exactly_at_max_elevation_returns_max_kelvin(self):
        """Elevation exactly at max returns max_kelvin."""
        result = calculate_kelvin_from_elevation(
            elevation=60,  # Exactly at default max
            min_kelvin=2700,
            max_kelvin=6500,
        )
        assert result.kelvin == 6500

    # --- Interpolation ---

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

    def test_sunrise_elevation_interpolation(self):
        """Sunrise/sunset (~0°) produces intermediate warm color."""
        result = calculate_kelvin_from_elevation(
            elevation=0,
            min_kelvin=2700,
            max_kelvin=6500,
        )
        # t = (0 - (-20)) / (60 - (-20)) = 20/80 = 0.25
        # kelvin = 2700 + 3800 * 0.25 = 2700 + 950 = 3650
        assert result.kelvin == 3650

    def test_low_positive_elevation(self):
        """Low positive elevation (morning/evening sun)."""
        result = calculate_kelvin_from_elevation(
            elevation=10,
            min_kelvin=2700,
            max_kelvin=6500,
        )
        # t = (10 - (-20)) / 80 = 30/80 = 0.375
        # kelvin = 2700 + 3800 * 0.375 = 2700 + 1425 = 4125
        assert result.kelvin == 4125

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

    # --- Custom elevation ranges ---

    def test_custom_elevation_range(self):
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

    # --- Custom Kelvin ranges ---

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

    # --- Result metadata ---

    def test_result_contains_sun_elevation(self):
        """Result contains the original sun elevation value."""
        result = calculate_kelvin_from_elevation(
            elevation=25.5,
            min_kelvin=2700,
            max_kelvin=6500,
        )
        assert result.sun_elevation == 25.5

    def test_result_source_circadian_for_interpolation(self):
        """Source is 'circadian' for interpolated values."""
        result = calculate_kelvin_from_elevation(
            elevation=20,
            min_kelvin=2700,
            max_kelvin=6500,
        )
        assert result.source == "circadian"


# ===================================================================
#  clamp_kelvin
# ===================================================================


class TestClampKelvin:
    """Tests for clamp_kelvin function."""

    def test_value_within_range_unchanged(self):
        """Value within range is returned unchanged."""
        assert clamp_kelvin(4000, 2700, 6500) == 4000

    def test_value_above_max_clamped(self):
        """Value above max is clamped to max."""
        assert clamp_kelvin(8000, 2700, 6500) == 6500

    def test_value_below_min_clamped(self):
        """Value below min is clamped to min."""
        assert clamp_kelvin(2000, 2700, 6500) == 2700

    def test_boundary_values(self):
        """Boundary values are handled correctly."""
        assert clamp_kelvin(2700, 2700, 6500) == 2700
        assert clamp_kelvin(6500, 2700, 6500) == 6500

    def test_narrow_range(self):
        """Narrow range works correctly."""
        assert clamp_kelvin(2800, 2700, 3000) == 2800
        assert clamp_kelvin(2500, 2700, 3000) == 2700
        assert clamp_kelvin(3500, 2700, 3000) == 3000


# ===================================================================
#  mix_kelvin
# ===================================================================


class TestMixKelvin:
    """Tests for mix_kelvin function."""

    def test_ratio_zero_returns_first(self):
        """Ratio 0.0 returns first Kelvin value."""
        assert mix_kelvin(2700, 6500, 0.0) == 2700

    def test_ratio_one_returns_second(self):
        """Ratio 1.0 returns second Kelvin value."""
        assert mix_kelvin(2700, 6500, 1.0) == 6500

    def test_ratio_half_returns_midpoint(self):
        """Ratio 0.5 returns midpoint."""
        # (2700 + 6500) / 2 = 4600
        assert mix_kelvin(2700, 6500, 0.5) == 4600

    def test_ratio_quarter(self):
        """Ratio 0.25 returns 25% toward second value."""
        # 2700 + (6500-2700) * 0.25 = 2700 + 950 = 3650
        assert mix_kelvin(2700, 6500, 0.25) == 3650

    def test_ratio_three_quarters(self):
        """Ratio 0.75 returns 75% toward second value."""
        # 2700 + (6500-2700) * 0.75 = 2700 + 2850 = 5550
        assert mix_kelvin(2700, 6500, 0.75) == 5550

    def test_negative_ratio_clamped_to_zero(self):
        """Negative ratio is clamped to 0."""
        assert mix_kelvin(2700, 6500, -0.5) == 2700

    def test_ratio_above_one_clamped_to_one(self):
        """Ratio > 1.0 is clamped to 1.0."""
        assert mix_kelvin(2700, 6500, 1.5) == 6500

    def test_same_values_returns_same(self):
        """Mixing same values returns that value."""
        assert mix_kelvin(4000, 4000, 0.5) == 4000

    def test_reverse_order(self):
        """Mixing in reverse order (high to low) works."""
        # 6500 + (2700-6500) * 0.5 = 6500 - 1900 = 4600
        assert mix_kelvin(6500, 2700, 0.5) == 4600


# ===================================================================
#  Default constants validation
# ===================================================================


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
