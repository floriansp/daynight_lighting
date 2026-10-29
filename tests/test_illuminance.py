"""Tests for IlluminanceReader — LUX reading, smoothing, flapping detection."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import patch


from custom_components.daynight_lighting.illuminance import IlluminanceReader
from custom_components.daynight_lighting.config import IlluminanceConfig

from tests.conftest import FakeState


def _make_config(
    smoothing_samples: int = 3,
    brightness_change_threshold_pct: int = 3,
    flapping_freeze_min: int = 5,
) -> IlluminanceConfig:
    """Create an IlluminanceConfig."""
    return IlluminanceConfig(
        smoothing_samples=smoothing_samples,
        brightness_change_threshold_pct=brightness_change_threshold_pct,
        flapping_freeze_min=flapping_freeze_min,
    )


def _make_reader(
    fake_hass,
    light_sensor: str | None = "sensor.lux",
    **config_kwargs,
) -> IlluminanceReader:
    """Create an IlluminanceReader."""
    config = _make_config(**config_kwargs)
    return IlluminanceReader(
        hass=fake_hass,
        config=config,
        instance_name="Test",
        light_sensor_entity_id=light_sensor,
    )


# ===================================================================
#  get_light_sensor_entity
# ===================================================================


class TestGetLightSensorEntity:
    """Tests for get_light_sensor_entity method."""

    def test_returns_configured_entity(self, fake_hass):
        """Returns the configured light sensor entity_id."""
        reader = _make_reader(fake_hass, light_sensor="sensor.my_lux")
        assert reader.get_light_sensor_entity() == "sensor.my_lux"

    def test_returns_none_when_not_configured(self, fake_hass):
        """Returns None when no light sensor configured."""
        reader = _make_reader(fake_hass, light_sensor=None)
        assert reader.get_light_sensor_entity() is None


# ===================================================================
#  get_lux_raw
# ===================================================================


class TestGetLuxRaw:
    """Tests for get_lux_raw method."""

    def test_no_sensor_configured(self, fake_hass):
        """Returns None when no sensor configured."""
        reader = _make_reader(fake_hass, light_sensor=None)
        assert reader.get_lux_raw() is None

    def test_no_sensor_configured_logs_once(self, fake_hass, caplog):
        """The 'no sensor' notice is logged once, not per read."""
        import logging
        reader = _make_reader(fake_hass, light_sensor=None)
        with caplog.at_level(logging.DEBUG, logger="custom_components.daynight_lighting.illuminance"):
            reader.get_lux_raw()
            reader.get_lux_raw()
            reader.get_lux_raw()
        notices = [
            r.getMessage()
            for r in caplog.records
            if "No light_sensor configured" in r.getMessage()
        ]
        assert len(notices) == 1

    def test_valid_lux_reading(self, fake_hass):
        """Returns float value from sensor state."""
        fake_hass.states.set("sensor.lux", FakeState(state="123.45"))
        reader = _make_reader(fake_hass)
        assert reader.get_lux_raw() == 123.45

    def test_integer_lux_reading(self, fake_hass):
        """Handles integer state values."""
        fake_hass.states.set("sensor.lux", FakeState(state="100"))
        reader = _make_reader(fake_hass)
        assert reader.get_lux_raw() == 100.0

    def test_sensor_unavailable(self, fake_hass):
        """Returns None when sensor is unavailable."""
        fake_hass.states.set("sensor.lux", FakeState(state="unavailable"))
        reader = _make_reader(fake_hass)
        assert reader.get_lux_raw() is None

    def test_sensor_unknown(self, fake_hass):
        """Returns None when sensor state is unknown."""
        fake_hass.states.set("sensor.lux", FakeState(state="unknown"))
        reader = _make_reader(fake_hass)
        assert reader.get_lux_raw() is None

    def test_sensor_missing(self, fake_hass):
        """Returns None when sensor entity doesn't exist."""
        reader = _make_reader(fake_hass)
        # Don't set the state
        assert reader.get_lux_raw() is None

    def test_non_numeric_state(self, fake_hass):
        """Returns None when state is not numeric."""
        fake_hass.states.set("sensor.lux", FakeState(state="bright"))
        reader = _make_reader(fake_hass)
        assert reader.get_lux_raw() is None

    def test_empty_state(self, fake_hass):
        """Returns None when state is empty."""
        fake_hass.states.set("sensor.lux", FakeState(state=""))
        reader = _make_reader(fake_hass)
        assert reader.get_lux_raw() is None

    def test_multiple_sensors_are_averaged(self, fake_hass):
        """The mean of all available sensors is returned."""
        fake_hass.states.set("sensor.lux1", FakeState(state="100"))
        fake_hass.states.set("sensor.lux2", FakeState(state="300"))
        reader = _make_reader(fake_hass, light_sensor=["sensor.lux1", "sensor.lux2"])
        assert reader.get_lux_raw() == 200.0

    def test_unavailable_sensor_is_skipped_in_average(self, fake_hass):
        """Only valid readings count towards the mean."""
        fake_hass.states.set("sensor.lux1", FakeState(state="100"))
        fake_hass.states.set("sensor.lux2", FakeState(state="unavailable"))
        reader = _make_reader(fake_hass, light_sensor=["sensor.lux1", "sensor.lux2"])
        assert reader.get_lux_raw() == 100.0


# ===================================================================
#  LUX calibration
# ===================================================================


class TestLuxCalibration:
    """Tests for LUX calibration methods."""

    def test_set_and_get_calibration(self, fake_hass):
        """set_lux_calibration stores value, get_lux_calibration retrieves it."""
        reader = _make_reader(fake_hass)
        reader.set_lux_calibration(150.5)
        assert reader.get_lux_calibration() == 150.5

    def test_calibration_none(self, fake_hass):
        """Default calibration is None."""
        reader = _make_reader(fake_hass)
        assert reader.get_lux_calibration() is None

    def test_calibration_none_explicit(self, fake_hass):
        """Can set calibration to None explicitly."""
        reader = _make_reader(fake_hass)
        reader.set_lux_calibration(100.0)
        reader.set_lux_calibration(None)
        assert reader.get_lux_calibration() is None


# ===================================================================
#  LUX smoothing
# ===================================================================


class TestLuxSmoothing:
    """Tests for LUX smoothing (rolling average)."""

    def test_single_sample_no_smoothing(self, fake_hass):
        """With 1 sample, returns raw value."""
        fake_hass.states.set("sensor.lux", FakeState(state="100"))
        reader = _make_reader(fake_hass, smoothing_samples=1)
        assert reader.get_lux() == 100.0

    def test_multiple_samples_averaged(self, fake_hass):
        """Multiple samples are averaged."""
        reader = _make_reader(fake_hass, smoothing_samples=3)

        # First sample: 100
        fake_hass.states.set("sensor.lux", FakeState(state="100"))
        result1 = reader.get_lux()
        assert result1 == 100.0

        # Second sample: 200
        fake_hass.states.set("sensor.lux", FakeState(state="200"))
        result2 = reader.get_lux()
        assert result2 == 150.0  # (100 + 200) / 2

        # Third sample: 300
        fake_hass.states.set("sensor.lux", FakeState(state="300"))
        result3 = reader.get_lux()
        assert result3 == 200.0  # (100 + 200 + 300) / 3

    def test_rolling_window(self, fake_hass):
        """Old samples drop out of the window."""
        reader = _make_reader(fake_hass, smoothing_samples=3)

        # Fill window
        fake_hass.states.set("sensor.lux", FakeState(state="100"))
        reader.get_lux()
        fake_hass.states.set("sensor.lux", FakeState(state="200"))
        reader.get_lux()
        fake_hass.states.set("sensor.lux", FakeState(state="300"))
        reader.get_lux()

        # Fourth sample: 400 (100 should drop out)
        fake_hass.states.set("sensor.lux", FakeState(state="400"))
        result = reader.get_lux()
        assert result == 300.0  # (200 + 300 + 400) / 3


# ===================================================================
#  LUX compensation
# ===================================================================


class TestLuxCompensation:
    """Tests for LUX compensation (subtracting lamp contribution)."""

    def test_no_compensation_without_calibration(self, fake_hass):
        """Without calibration, raw LUX is returned."""
        fake_hass.states.set("sensor.lux", FakeState(state="100"))
        reader = _make_reader(fake_hass)
        # No calibration set
        assert reader.get_lux() == 100.0

    def test_no_compensation_without_applied_brightness(self, fake_hass):
        """Without applied brightness, raw LUX is returned."""
        fake_hass.states.set("sensor.lux", FakeState(state="100"))
        reader = _make_reader(fake_hass)
        reader.set_lux_calibration(50.0)  # 50 LUX at 100%
        # No brightness applied yet
        assert reader.get_lux() == 100.0

    def test_compensation_applied(self, fake_hass):
        """Lamp contribution is subtracted when calibrated."""
        fake_hass.states.set("sensor.lux", FakeState(state="100"))
        reader = _make_reader(fake_hass)
        reader.set_lux_calibration(50.0)  # 50 LUX at 100%
        reader.record_brightness_applied(50)  # 50% brightness

        # Lamp contribution: 50 * 0.5 = 25 LUX
        # Ambient: 100 - 25 = 75 LUX
        assert reader.get_lux() == 75.0

    def test_compensation_clamped_to_zero(self, fake_hass):
        """Compensated LUX is clamped to non-negative."""
        fake_hass.states.set("sensor.lux", FakeState(state="10"))
        reader = _make_reader(fake_hass)
        reader.set_lux_calibration(100.0)  # 100 LUX at 100%
        reader.record_brightness_applied(100)  # 100% brightness

        # Lamp contribution: 100 * 1.0 = 100 LUX
        # Ambient: 10 - 100 = -90 → clamped to 0
        assert reader.get_lux() == 0.0

    def test_compensation_at_zero_brightness(self, fake_hass):
        """At 0% brightness, no lamp contribution subtracted."""
        fake_hass.states.set("sensor.lux", FakeState(state="100"))
        reader = _make_reader(fake_hass)
        reader.set_lux_calibration(50.0)
        reader.record_brightness_applied(0)  # 0% brightness

        # Lamp contribution: 50 * 0.0 = 0 LUX
        # Ambient: 100 - 0 = 100 LUX
        assert reader.get_lux() == 100.0


# ===================================================================
#  Brightness threshold
# ===================================================================


class TestBrightnessThreshold:
    """Tests for should_apply_brightness with change threshold."""

    def test_first_brightness_always_applies(self, fake_hass):
        """First brightness after init always applies."""
        reader = _make_reader(fake_hass, brightness_change_threshold_pct=10)
        assert reader.should_apply_brightness(50) is True

    def test_small_change_below_threshold(self, fake_hass):
        """Small changes below threshold don't apply."""
        reader = _make_reader(fake_hass, brightness_change_threshold_pct=10)
        reader.record_brightness_applied(50)
        assert reader.should_apply_brightness(55) is False  # 5% < 10%

    def test_exact_threshold_applies(self, fake_hass):
        """Change exactly at threshold applies."""
        reader = _make_reader(fake_hass, brightness_change_threshold_pct=10)
        reader.record_brightness_applied(50)
        assert reader.should_apply_brightness(60) is True  # 10% == 10%

    def test_above_threshold_applies(self, fake_hass):
        """Changes above threshold apply."""
        reader = _make_reader(fake_hass, brightness_change_threshold_pct=10)
        reader.record_brightness_applied(50)
        assert reader.should_apply_brightness(65) is True  # 15% > 10%

    def test_decrease_below_threshold(self, fake_hass):
        """Decreases below threshold don't apply."""
        reader = _make_reader(fake_hass, brightness_change_threshold_pct=10)
        reader.record_brightness_applied(50)
        assert reader.should_apply_brightness(45) is False  # 5% < 10%

    def test_decrease_above_threshold(self, fake_hass):
        """Decreases above threshold apply."""
        reader = _make_reader(fake_hass, brightness_change_threshold_pct=10)
        reader.record_brightness_applied(50)
        assert reader.should_apply_brightness(35) is True  # 15% > 10%


# ===================================================================
#  Flapping detection
# ===================================================================


class TestFlappingDetection:
    """Tests for flapping detection and freeze."""

    def test_no_flapping_with_few_samples(self, fake_hass):
        """No flapping detected with fewer than 4 samples."""
        reader = _make_reader(fake_hass)
        reader.record_brightness_applied(50)
        reader.record_brightness_applied(60)
        reader.record_brightness_applied(50)
        # Only 3 samples, no flapping
        assert reader.should_apply_brightness(70) is True

    def test_flapping_freeze_prevents_changes(self, fake_hass):
        """During flapping freeze, brightness changes are prevented."""
        from datetime import timedelta

        reader = _make_reader(fake_hass, flapping_freeze_min=5)

        # Fixed time for all calls
        now = datetime(2026, 6, 15, 10, 0, 0)

        with patch('custom_components.daynight_lighting.illuminance.datetime') as mock_dt:
            mock_dt.now.return_value = now
            mock_dt.timedelta = timedelta

            # Simulate oscillation with 5 values producing 3+ direction changes:
            # 50 -> 60 -> 50 -> 60 -> 50
            # Directions: +1, -1, +1, -1 (4 directions)
            # Changes: 3 (up->down, down->up, up->down)
            reader.record_brightness_applied(50)
            reader.record_brightness_applied(60)  # up
            reader.record_brightness_applied(50)  # down
            reader.record_brightness_applied(60)  # up
            reader.record_brightness_applied(50)  # down (3 direction changes)

            # Flapping should be detected, freeze active
            assert reader.should_apply_brightness(70) is False

    def test_flapping_freeze_expires(self, fake_hass):
        """After freeze period, changes are allowed again."""
        from datetime import timedelta

        reader = _make_reader(fake_hass, flapping_freeze_min=0)

        # Fixed time for all calls
        now = datetime(2026, 6, 15, 10, 0, 0)
        later = datetime(2026, 6, 15, 10, 0, 1)  # 1 second later

        with patch('custom_components.daynight_lighting.illuminance.datetime') as mock_dt:
            mock_dt.now.return_value = now
            mock_dt.timedelta = timedelta

            # Simulate oscillation
            reader.record_brightness_applied(50)
            reader.record_brightness_applied(60)
            reader.record_brightness_applied(50)
            reader.record_brightness_applied(60)
            reader.record_brightness_applied(50)

            # With flapping_freeze_min=0, the freeze_until = now + 0 = now
            # Check after a small time delta to ensure now > freeze_until
            mock_dt.now.return_value = later
            # With freeze expired, changes are allowed
            assert reader.should_apply_brightness(70) is True

    def test_no_flapping_with_same_direction(self, fake_hass):
        """Consistent direction changes are not flapping."""
        from datetime import timedelta

        reader = _make_reader(fake_hass)

        # Fixed time for all calls
        now = datetime(2026, 6, 15, 10, 0, 0)

        with patch('custom_components.daynight_lighting.illuminance.datetime') as mock_dt:
            mock_dt.now.return_value = now
            mock_dt.timedelta = timedelta

            # Consistent increases: 50 -> 60 -> 70 -> 80
            reader.record_brightness_applied(50)
            reader.record_brightness_applied(60)  # up
            reader.record_brightness_applied(70)  # up
            reader.record_brightness_applied(80)  # up

        # No direction changes, no flapping
        assert reader.should_apply_brightness(90) is True


# ===================================================================
#  clear_state
# ===================================================================


class TestClearState:
    """Tests for clear_state method."""

    def test_clears_all_state(self, fake_hass):
        """clear_state resets all internal state."""
        reader = _make_reader(fake_hass)

        # Set up some state
        fake_hass.states.set("sensor.lux", FakeState(state="100"))
        reader.get_lux()  # Add samples
        reader.record_brightness_applied(50)
        reader.set_lux_calibration(100.0)

        # Clear state
        reader.clear_state()

        # All state should be reset
        assert len(reader._lux_samples) == 0
        assert reader._last_applied_brightness_pct is None
        assert len(reader._brightness_history) == 0
        assert reader._flapping_freeze_until is None
        # Calibration is preserved (not cleared)
        assert reader.get_lux_calibration() == 100.0
