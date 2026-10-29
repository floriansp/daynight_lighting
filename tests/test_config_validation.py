"""Tests for configuration dataclass validation.

Tests the __post_init__ validators that catch invalid configuration values
at configuration load time.
"""

import pytest

from custom_components.daynight_lighting.config import (
    CircadianConfig,
    DayModeConfig,
    IlluminanceConfig,
    NightModeConfig,
    SleepModeConfig,
    WakeUpModeConfig,
)


class TestDayModeConfigValidation:
    """Tests for DayModeConfig validation."""

    def test_valid_config_passes(self):
        """Valid configuration passes validation."""
        config = DayModeConfig(
            lux_on=10.0,
            lux_off=100.0,
            min_brightness=10,
            max_brightness=100,
        )
        assert config.lux_on == 10.0
        assert config.lux_off == 100.0

    def test_reversed_lux_on_off_raises(self):
        """lux_on >= lux_off raises ValueError."""
        with pytest.raises(ValueError, match="lux_on.*must be < lux_off"):
            DayModeConfig(lux_on=100.0, lux_off=10.0)

    def test_equal_lux_on_off_raises(self):
        """lux_on == lux_off raises ValueError."""
        with pytest.raises(ValueError, match="lux_on.*must be < lux_off"):
            DayModeConfig(lux_on=50.0, lux_off=50.0)

    def test_min_brightness_below_zero_raises(self):
        """min_brightness < 0 raises ValueError."""
        with pytest.raises(ValueError, match="min_brightness.*must be 0-100"):
            DayModeConfig(min_brightness=-1)

    def test_min_brightness_above_100_raises(self):
        """min_brightness > 100 raises ValueError."""
        with pytest.raises(ValueError, match="min_brightness.*must be 0-100"):
            DayModeConfig(min_brightness=101)

    def test_max_brightness_below_zero_raises(self):
        """max_brightness < 0 raises ValueError."""
        with pytest.raises(ValueError, match="max_brightness.*must be 0-100"):
            DayModeConfig(max_brightness=-1)

    def test_max_brightness_above_100_raises(self):
        """max_brightness > 100 raises ValueError."""
        with pytest.raises(ValueError, match="max_brightness.*must be 0-100"):
            DayModeConfig(max_brightness=101)

    def test_min_greater_than_max_raises(self):
        """min_brightness > max_brightness raises ValueError."""
        with pytest.raises(ValueError, match="min_brightness.*must be <= max_brightness"):
            DayModeConfig(min_brightness=80, max_brightness=20)

    def test_fixed_brightness_out_of_range_raises(self):
        """fixed_brightness_pct out of range raises ValueError."""
        with pytest.raises(ValueError, match="fixed_brightness_pct.*must be 0-100"):
            DayModeConfig(fixed_brightness_pct=-5)

        with pytest.raises(ValueError, match="fixed_brightness_pct.*must be 0-100"):
            DayModeConfig(fixed_brightness_pct=150)


class TestNightModeConfigValidation:
    """Tests for NightModeConfig validation."""

    def test_valid_config_passes(self):
        """Valid configuration passes validation."""
        config = NightModeConfig(brightness=50, motion_off_delay_min=5)
        assert config.brightness == 50

    def test_brightness_below_zero_raises(self):
        """brightness < 0 raises ValueError."""
        with pytest.raises(ValueError, match="brightness.*must be 0-100"):
            NightModeConfig(brightness=-1)

    def test_brightness_above_100_raises(self):
        """brightness > 100 raises ValueError."""
        with pytest.raises(ValueError, match="brightness.*must be 0-100"):
            NightModeConfig(brightness=101)

    def test_negative_motion_off_delay_raises(self):
        """motion_off_delay_min < 0 raises ValueError."""
        with pytest.raises(ValueError, match="motion_off_delay_min.*must be >= 0"):
            NightModeConfig(motion_off_delay_min=-1)


class TestCircadianConfigValidation:
    """Tests for CircadianConfig validation."""

    def test_valid_config_passes(self):
        """Valid configuration passes validation."""
        config = CircadianConfig(min_kelvin=2700, max_kelvin=6500)
        assert config.min_kelvin == 2700
        assert config.max_kelvin == 6500

    def test_reversed_kelvin_raises(self):
        """min_kelvin >= max_kelvin raises ValueError."""
        with pytest.raises(ValueError, match="min_kelvin.*must be < max_kelvin"):
            CircadianConfig(min_kelvin=6500, max_kelvin=2700)

    def test_equal_kelvin_raises(self):
        """min_kelvin == max_kelvin raises ValueError."""
        with pytest.raises(ValueError, match="min_kelvin.*must be < max_kelvin"):
            CircadianConfig(min_kelvin=4000, max_kelvin=4000)

    def test_kelvin_below_1000_raises(self):
        """min_kelvin < 1000 raises ValueError."""
        with pytest.raises(ValueError, match="min_kelvin.*must be >= 1000K"):
            CircadianConfig(min_kelvin=500)


class TestSleepModeConfigValidation:
    """Tests for SleepModeConfig validation."""

    def test_valid_config_passes(self):
        """Valid configuration passes validation."""
        config = SleepModeConfig(
            target_brightness=10,
            target_kelvin=2200,
            duration_min=60,
        )
        assert config.target_brightness == 10

    def test_target_brightness_out_of_range_raises(self):
        """target_brightness out of range raises ValueError."""
        with pytest.raises(ValueError, match="target_brightness.*must be 0-100"):
            SleepModeConfig(target_brightness=-1)

        with pytest.raises(ValueError, match="target_brightness.*must be 0-100"):
            SleepModeConfig(target_brightness=101)

    def test_target_kelvin_below_1000_raises(self):
        """target_kelvin < 1000 raises ValueError."""
        with pytest.raises(ValueError, match="target_kelvin.*must be >= 1000K"):
            SleepModeConfig(target_kelvin=500)

    def test_duration_below_1_raises(self):
        """duration_min < 1 raises ValueError."""
        with pytest.raises(ValueError, match="duration_min.*must be >= 1"):
            SleepModeConfig(duration_min=0)


class TestWakeUpModeConfigValidation:
    """Tests for WakeUpModeConfig validation."""

    def test_valid_config_passes(self):
        """Valid configuration passes validation."""
        config = WakeUpModeConfig(start_brightness=1, duration_min=30)
        assert config.start_brightness == 1

    def test_start_brightness_out_of_range_raises(self):
        """start_brightness out of range raises ValueError."""
        with pytest.raises(ValueError, match="start_brightness.*must be 0-100"):
            WakeUpModeConfig(start_brightness=-1)

        with pytest.raises(ValueError, match="start_brightness.*must be 0-100"):
            WakeUpModeConfig(start_brightness=101)

    def test_duration_below_1_raises(self):
        """duration_min < 1 raises ValueError."""
        with pytest.raises(ValueError, match="duration_min.*must be >= 1"):
            WakeUpModeConfig(duration_min=0)


class TestIlluminanceConfigValidation:
    """Tests for IlluminanceConfig validation."""

    def test_valid_config_passes(self):
        """Valid configuration passes validation."""
        config = IlluminanceConfig(
            smoothing_samples=5,
            brightness_change_threshold_pct=5,
            flapping_freeze_min=2,
        )
        assert config.smoothing_samples == 5

    def test_smoothing_samples_below_1_raises(self):
        """smoothing_samples < 1 raises ValueError."""
        with pytest.raises(ValueError, match="smoothing_samples.*must be >= 1"):
            IlluminanceConfig(smoothing_samples=0)

    def test_brightness_threshold_out_of_range_raises(self):
        """brightness_change_threshold_pct out of range raises ValueError."""
        with pytest.raises(ValueError, match="brightness_change_threshold_pct.*must be 0-100"):
            IlluminanceConfig(brightness_change_threshold_pct=-1)

        with pytest.raises(ValueError, match="brightness_change_threshold_pct.*must be 0-100"):
            IlluminanceConfig(brightness_change_threshold_pct=101)

    def test_negative_flapping_freeze_raises(self):
        """flapping_freeze_min < 0 raises ValueError."""
        with pytest.raises(ValueError, match="flapping_freeze_min.*must be >= 0"):
            IlluminanceConfig(flapping_freeze_min=-1)
