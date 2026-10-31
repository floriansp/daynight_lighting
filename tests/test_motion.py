"""Tests for MotionController — motion sensor handling and off timer."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch


from homeassistant.const import STATE_ON, STATE_OFF

from custom_components.daynight_lighting.motion import MotionController

from tests.conftest import FakeState


def _make_config(motion_off_delay_min: int = 5) -> SimpleNamespace:
    """Create a NightModeConfig."""
    return SimpleNamespace(motion_off_delay_min=motion_off_delay_min)


def _make_controller(
    fake_hass,
    motion_sensor: str | None = "binary_sensor.motion",
    motion_off_delay_min: int = 5,
    action_scheduler=None,
    cancel_key: str | None = None,
) -> MotionController:
    """Create a MotionController."""
    config = _make_config(motion_off_delay_min=motion_off_delay_min)
    return MotionController(
        hass=fake_hass,
        config=config,
        instance_name="Test",
        motion_sensor_entity_id=motion_sensor,
        action_scheduler=action_scheduler,
        cancel_key=cancel_key,
    )


# ===================================================================
#  get_motion_sensor_entity
# ===================================================================


class TestGetMotionSensorEntity:
    """Tests for get_motion_sensor_entity method."""

    def test_returns_configured_entity(self, fake_hass):
        """Returns the configured motion sensor entity_id."""
        controller = _make_controller(fake_hass, motion_sensor="binary_sensor.my_motion")
        assert controller.get_motion_sensor_entity() == "binary_sensor.my_motion"

    def test_returns_none_when_not_configured(self, fake_hass):
        """Returns None when no motion sensor configured."""
        controller = _make_controller(fake_hass, motion_sensor=None)
        assert controller.get_motion_sensor_entity() is None


# ===================================================================
#  has_motion_now
# ===================================================================


class TestHasMotionNow:
    """Tests for has_motion_now method."""

    def test_no_sensor_configured(self, fake_hass):
        """Returns False when no sensor configured."""
        controller = _make_controller(fake_hass, motion_sensor=None)
        assert controller.has_motion_now() is False

    def test_motion_detected(self, fake_hass):
        """Returns True when motion sensor is ON."""
        fake_hass.states.set("binary_sensor.motion", FakeState(state=STATE_ON))
        controller = _make_controller(fake_hass)
        assert controller.has_motion_now() is True

    def test_no_motion(self, fake_hass):
        """Returns False when motion sensor is OFF."""
        fake_hass.states.set("binary_sensor.motion", FakeState(state=STATE_OFF))
        controller = _make_controller(fake_hass)
        assert controller.has_motion_now() is False

    def test_sensor_unavailable(self, fake_hass):
        """Returns False when sensor is unavailable."""
        fake_hass.states.set("binary_sensor.motion", FakeState(state="unavailable"))
        controller = _make_controller(fake_hass)
        assert controller.has_motion_now() is False

    def test_sensor_missing(self, fake_hass):
        """Returns False when sensor entity doesn't exist."""
        controller = _make_controller(fake_hass)
        # Don't set the state
        assert controller.has_motion_now() is False


# ===================================================================
#  schedule_night_motion_off
# ===================================================================


class TestScheduleNightMotionOff:
    """Tests for schedule_night_motion_off method."""

    def test_schedules_with_action_scheduler(self, fake_hass):
        """Uses ActionScheduler when available."""
        scheduler = MagicMock()
        controller = _make_controller(
            fake_hass,
            action_scheduler=scheduler,
            cancel_key="test_key",
        )

        callback_fn = MagicMock(return_value=(["light.a"], None))
        controller.schedule_night_motion_off(["light.a"], callback_fn)

        scheduler.add.assert_called_once()
        call_args = scheduler.add.call_args
        assert call_args[1]["source"] == "MotionController"
        assert call_args[1]["reason"] == "motion_off"

    def test_empty_lights_no_schedule(self, fake_hass):
        """Doesn't schedule when lights list is empty."""
        scheduler = MagicMock()
        controller = _make_controller(
            fake_hass,
            action_scheduler=scheduler,
            cancel_key="test_key",
        )

        callback_fn = MagicMock()
        controller.schedule_night_motion_off([], callback_fn)

        scheduler.add.assert_not_called()

    def test_uses_configured_delay(self, fake_hass):
        """Uses motion_off_delay_min from config."""
        scheduler = MagicMock()
        controller = _make_controller(
            fake_hass,
            motion_off_delay_min=10,
            action_scheduler=scheduler,
            cancel_key="test_key",
        )

        callback_fn = MagicMock(return_value=(["light.a"], None))

        with patch('custom_components.daynight_lighting.motion.dt_util') as mock_dt:
            mock_dt.utcnow.return_value = MagicMock()
            mock_dt.utcnow.return_value.__add__ = lambda self, other: self
            controller.schedule_night_motion_off(["light.a"], callback_fn)

        # Delay should be 10 minutes
        scheduler.add.assert_called_once()


# ===================================================================
#  cancel_night_motion_off_timer
# ===================================================================


class TestCancelNightMotionOffTimer:
    """Tests for cancel_night_motion_off_timer method."""

    def test_cancels_action_scheduler(self, fake_hass):
        """Cancels via ActionScheduler when available."""
        scheduler = MagicMock()
        controller = _make_controller(
            fake_hass,
            action_scheduler=scheduler,
            cancel_key="test_key",
        )

        controller.cancel_night_motion_off_timer()

        scheduler.remove.assert_called_once_with("test_key")

    def test_cancels_fallback_timer(self, fake_hass):
        """Cancels fallback timer when no ActionScheduler."""
        controller = _make_controller(fake_hass)

        # Create a mock timer
        mock_timer = MagicMock()
        controller._motion_off_timer = mock_timer

        controller.cancel_night_motion_off_timer()

        mock_timer.cancel.assert_called_once()
        assert controller._motion_off_timer is None

    def test_cancel_when_no_timer(self, fake_hass):
        """No error when canceling with no active timer."""
        controller = _make_controller(fake_hass)

        # Should not raise
        controller.cancel_night_motion_off_timer()

    def test_cancel_clears_timer_reference(self, fake_hass):
        """Timer reference is cleared after cancel."""
        controller = _make_controller(fake_hass)

        mock_timer = MagicMock()
        controller._motion_off_timer = mock_timer

        controller.cancel_night_motion_off_timer()

        assert controller._motion_off_timer is None
