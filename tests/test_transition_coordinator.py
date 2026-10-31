"""Tests for TransitionCoordinator — mode transition logic.

Tests the transition_sync method and specific transition handlers
for day/night/sleep/wake mode changes.
"""

from __future__ import annotations

from unittest.mock import MagicMock


from custom_components.daynight_lighting.const import (
    MODE_DAY,
    MODE_NIGHT,
    MODE_SLEEP,
    MODE_WAKEUP,
)
from custom_components.daynight_lighting.transition_coordinator import (
    TransitionCoordinator,
)


def _make_mock_handler():
    """Create a mock mode handler."""
    handler = MagicMock()
    handler.enter = MagicMock()
    handler.exit = MagicMock()
    handler.tick = MagicMock()
    handler.is_sleep_active = MagicMock(return_value=False)
    handler.is_active = MagicMock(return_value=False)
    handler.is_block_active = MagicMock(return_value=False)
    return handler


def _make_coordinator(fake_hass) -> TransitionCoordinator:
    """Create a TransitionCoordinator with mocked dependencies."""
    handlers = {
        MODE_DAY: _make_mock_handler(),
        MODE_NIGHT: _make_mock_handler(),
        MODE_SLEEP: _make_mock_handler(),
        MODE_WAKEUP: _make_mock_handler(),
    }

    lights = MagicMock()
    lights.get_lights_list = MagicMock(return_value=["light.a", "light.b"])

    motion = MagicMock()

    state_ctrl = MagicMock()
    state_ctrl.mark_controlled = MagicMock()
    state_ctrl.unmark_controlled = MagicMock()
    state_ctrl.set_expected_state = MagicMock()

    return TransitionCoordinator(
        hass=fake_hass,
        instance_name="Test",
        handlers=handlers,
        lights=lights,
        motion=motion,
        state_ctrl=state_ctrl,
        get_transition=lambda ctx: 0,
        is_control_brightness_on=lambda: True,
        is_control_color_on=lambda: True,
    )


# ===================================================================
#  Basic transition tests
# ===================================================================


class TestTransitionCoordinatorBasic:
    """Basic transition coordinator tests."""

    def test_transition_sync_calls_exit_on_old_handler(self, fake_hass):
        """transition_sync calls exit() on the old mode handler."""
        coordinator = _make_coordinator(fake_hass)

        coordinator.transition_sync(MODE_DAY, MODE_NIGHT)

        coordinator._handlers[MODE_DAY].exit.assert_called_once_with(MODE_NIGHT)

    def test_transition_sync_calls_enter_on_new_handler(self, fake_hass):
        """transition_sync calls enter() on the new mode handler."""
        coordinator = _make_coordinator(fake_hass)

        coordinator.transition_sync(MODE_DAY, MODE_NIGHT)

        coordinator._handlers[MODE_NIGHT].enter.assert_called_once_with(MODE_DAY)

    def test_transition_sync_handles_unknown_from_mode(self, fake_hass):
        """transition_sync handles transitions from unknown modes gracefully."""
        coordinator = _make_coordinator(fake_hass)

        # Transition from non-existent mode
        coordinator.transition_sync("unknown", MODE_DAY)

        # Should not raise, should call enter on new handler
        coordinator._handlers[MODE_DAY].enter.assert_called_once_with("unknown")

    def test_transition_sync_handles_unknown_to_mode(self, fake_hass):
        """transition_sync handles transitions to unknown modes gracefully."""
        coordinator = _make_coordinator(fake_hass)

        # Transition to non-existent mode
        coordinator.transition_sync(MODE_DAY, "unknown")

        # Exit should still be called
        coordinator._handlers[MODE_DAY].exit.assert_called_once_with("unknown")


# ===================================================================
#  Specific transition tests
# ===================================================================


class TestDayToNightTransition:
    """Tests for Day -> Night transition."""

    def test_day_to_night_transition(self, fake_hass):
        """Day to night transition calls correct handlers."""
        coordinator = _make_coordinator(fake_hass)

        coordinator.transition_sync(MODE_DAY, MODE_NIGHT)

        coordinator._handlers[MODE_DAY].exit.assert_called_once_with(MODE_NIGHT)
        coordinator._handlers[MODE_NIGHT].enter.assert_called_once_with(MODE_DAY)


class TestNightToDayTransition:
    """Tests for Night -> Day transition."""

    def test_night_to_day_transition(self, fake_hass):
        """Night to day transition calls correct handlers."""
        coordinator = _make_coordinator(fake_hass)

        coordinator.transition_sync(MODE_NIGHT, MODE_DAY)

        coordinator._handlers[MODE_NIGHT].exit.assert_called_once_with(MODE_DAY)
        coordinator._handlers[MODE_DAY].enter.assert_called_once_with(MODE_NIGHT)


class TestDayToSleepTransition:
    """Tests for Day -> Sleep transition."""

    def test_day_to_sleep_transition(self, fake_hass):
        """Day to sleep transition calls correct handlers."""
        coordinator = _make_coordinator(fake_hass)

        coordinator.transition_sync(MODE_DAY, MODE_SLEEP)

        coordinator._handlers[MODE_DAY].exit.assert_called_once_with(MODE_SLEEP)
        coordinator._handlers[MODE_SLEEP].enter.assert_called_once_with(MODE_DAY)


class TestSleepToNightTransition:
    """Tests for Sleep -> Night transition."""

    def test_sleep_to_night_transition(self, fake_hass):
        """Sleep to night transition calls correct handlers."""
        coordinator = _make_coordinator(fake_hass)

        coordinator.transition_sync(MODE_SLEEP, MODE_NIGHT)

        coordinator._handlers[MODE_SLEEP].exit.assert_called_once_with(MODE_NIGHT)
        coordinator._handlers[MODE_NIGHT].enter.assert_called_once_with(MODE_SLEEP)


class TestNightToWakeUpTransition:
    """Tests for Night -> WakeUp transition."""

    def test_night_to_wakeup_transition(self, fake_hass):
        """Night to wake-up transition calls correct handlers."""
        coordinator = _make_coordinator(fake_hass)

        coordinator.transition_sync(MODE_NIGHT, MODE_WAKEUP)

        coordinator._handlers[MODE_NIGHT].exit.assert_called_once_with(MODE_WAKEUP)
        coordinator._handlers[MODE_WAKEUP].enter.assert_called_once_with(MODE_NIGHT)


class TestWakeUpToDayTransition:
    """Tests for WakeUp -> Day transition."""

    def test_wakeup_to_day_transition(self, fake_hass):
        """Wake-up to day transition calls correct handlers."""
        coordinator = _make_coordinator(fake_hass)

        coordinator.transition_sync(MODE_WAKEUP, MODE_DAY)

        coordinator._handlers[MODE_WAKEUP].exit.assert_called_once_with(MODE_DAY)
        coordinator._handlers[MODE_DAY].enter.assert_called_once_with(MODE_WAKEUP)


class TestWakeUpToNightTransition:
    """Tests for WakeUp -> Night transition (early wake-up end)."""

    def test_wakeup_to_night_transition(self, fake_hass):
        """Wake-up to night transition (when wake-up ends before sunrise)."""
        coordinator = _make_coordinator(fake_hass)

        coordinator.transition_sync(MODE_WAKEUP, MODE_NIGHT)

        coordinator._handlers[MODE_WAKEUP].exit.assert_called_once_with(MODE_NIGHT)
        coordinator._handlers[MODE_NIGHT].enter.assert_called_once_with(MODE_WAKEUP)


# ===================================================================
#  Round-trip transitions
# ===================================================================


class TestRoundTripTransitions:
    """Tests for sequences of transitions."""

    def test_day_night_day_cycle(self, fake_hass):
        """Complete day -> night -> day cycle."""
        coordinator = _make_coordinator(fake_hass)

        # Day -> Night
        coordinator.transition_sync(MODE_DAY, MODE_NIGHT)
        assert coordinator._handlers[MODE_DAY].exit.call_count == 1
        assert coordinator._handlers[MODE_NIGHT].enter.call_count == 1

        # Night -> Day
        coordinator.transition_sync(MODE_NIGHT, MODE_DAY)
        assert coordinator._handlers[MODE_NIGHT].exit.call_count == 1
        assert coordinator._handlers[MODE_DAY].enter.call_count == 1

    def test_full_day_cycle_with_sleep(self, fake_hass):
        """Day -> Sleep -> Night -> WakeUp -> Day."""
        coordinator = _make_coordinator(fake_hass)

        # Day -> Sleep
        coordinator.transition_sync(MODE_DAY, MODE_SLEEP)

        # Sleep -> Night
        coordinator.transition_sync(MODE_SLEEP, MODE_NIGHT)

        # Night -> WakeUp
        coordinator.transition_sync(MODE_NIGHT, MODE_WAKEUP)

        # WakeUp -> Day
        coordinator.transition_sync(MODE_WAKEUP, MODE_DAY)

        # Each handler should have been exited and entered once
        assert coordinator._handlers[MODE_DAY].exit.call_count == 1
        assert coordinator._handlers[MODE_DAY].enter.call_count == 1
        assert coordinator._handlers[MODE_SLEEP].exit.call_count == 1
        assert coordinator._handlers[MODE_SLEEP].enter.call_count == 1
        assert coordinator._handlers[MODE_NIGHT].exit.call_count == 1
        assert coordinator._handlers[MODE_NIGHT].enter.call_count == 1
        assert coordinator._handlers[MODE_WAKEUP].exit.call_count == 1
        assert coordinator._handlers[MODE_WAKEUP].enter.call_count == 1


# ===================================================================
#  Edge cases
# ===================================================================


class TestTransitionEdgeCases:
    """Edge case tests for transitions."""

    def test_same_mode_transition(self, fake_hass):
        """Transition from a mode to itself."""
        coordinator = _make_coordinator(fake_hass)

        # Day -> Day (should still call exit/enter)
        coordinator.transition_sync(MODE_DAY, MODE_DAY)

        # Both should be called with MODE_DAY
        coordinator._handlers[MODE_DAY].exit.assert_called_once_with(MODE_DAY)
        coordinator._handlers[MODE_DAY].enter.assert_called_once_with(MODE_DAY)

    def test_multiple_transitions_same_session(self, fake_hass):
        """Multiple transitions in quick succession."""
        coordinator = _make_coordinator(fake_hass)

        # Rapid transitions
        coordinator.transition_sync(MODE_DAY, MODE_NIGHT)
        coordinator.transition_sync(MODE_NIGHT, MODE_DAY)
        coordinator.transition_sync(MODE_DAY, MODE_NIGHT)

        # Handlers should be called for each transition
        assert coordinator._handlers[MODE_DAY].exit.call_count == 2
        assert coordinator._handlers[MODE_DAY].enter.call_count == 1
        assert coordinator._handlers[MODE_NIGHT].exit.call_count == 1
        assert coordinator._handlers[MODE_NIGHT].enter.call_count == 2

    def test_transition_with_none_from_mode(self, fake_hass):
        """Transition from None (initial state)."""
        coordinator = _make_coordinator(fake_hass)

        coordinator.transition_sync(None, MODE_DAY)

        # Enter should be called with None as previous mode
        coordinator._handlers[MODE_DAY].enter.assert_called_once_with(None)
