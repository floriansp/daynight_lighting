"""Functional tests: Day ↔ Night transitions in DayNightLightingSwitch."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import patch


from custom_components.daynight_lighting.const import MODE_DAY, MODE_NIGHT

from tests.conftest import FakeState


class TestDayToNightTransition:
    """Tests for Day→Night transition via TransitionCoordinator."""

    def test_leave_mode_no_service_call_on_transition(self, make_switch, fake_hass):
        """on_enter_night='leave' → no turn_off call during transition."""
        switch, *_ = make_switch(
            options={"on_enter_night": "leave"}, day_mode=False
        )

        # Get night handler and call enter (simulates transition)
        night_handler = switch._get_mode_handler(MODE_NIGHT)
        night_handler.enter(MODE_DAY)

        # With 'leave' mode, no explicit turn_off should be called
        # (lights are left as-is)
        fake_hass.services.async_call.assert_not_called()

    def test_motion_active_at_transition_applies_night(
        self, make_switch, fake_hass
    ):
        """Motion already ON at transition → night values applied."""
        switch, *_ = make_switch(
            options={"on_enter_night": "leave"}, day_mode=False
        )
        fake_hass.states.set(
            "binary_sensor.motion", FakeState(state="on")
        )

        # Get night handler and call enter (simulates transition)
        with patch('custom_components.daynight_lighting.schedule.dt_util') as mock_dt:
            mock_dt.now.return_value = datetime(2026, 6, 15, 23, 0, 0)
            mock_dt.as_local.return_value = datetime(2026, 6, 15, 23, 0, 0)
            night_handler = switch._get_mode_handler(MODE_NIGHT)
            night_handler.enter(MODE_DAY)

        # Should have called light.turn_on with night payload
        calls = fake_hass.services.async_call.call_args_list
        turn_on_calls = [c for c in calls if c[0][1] == "turn_on"]
        assert len(turn_on_calls) >= 1

    def test_turn_off_mode_with_motion_active_does_not_flicker(
        self, make_switch, fake_hass
    ):
        """Presence at a turn_off transition re-applies night, no off flicker.

        With ``on_enter_night="turn_off"`` and motion already ON, the lights
        must not be switched off and straight back on: they are re-applied to
        the night target instead.
        """
        switch, *_ = make_switch(
            options={"on_enter_night": "turn_off"}, day_mode=False
        )
        switch._state_ctrl.mark_controlled(["light.a"])
        fake_hass.states.set("binary_sensor.motion", FakeState(state="on"))
        fake_hass.states.set(
            "light.a",
            FakeState(state="on", attributes={"brightness": 92, "color_temp": 225}),
        )
        fake_hass.states.set("light.b", FakeState(state="off"))

        night_handler = switch._get_mode_handler(MODE_NIGHT)
        night_handler.enter(MODE_DAY)

        calls = fake_hass.services.async_call.call_args_list
        turn_off_calls = [c for c in calls if c[0][1] == "turn_off"]
        turn_on_calls = [c for c in calls if c[0][1] == "turn_on"]
        assert turn_off_calls == []
        assert len(turn_on_calls) == 1
        assert "light.a" in turn_on_calls[0][0][2]["entity_id"]

    def test_turn_off_mode_with_motion_stays_controllable(
        self, make_switch, fake_hass
    ):
        """Lights re-applied at a turn_off transition are not held.

        They stay controlled, so once the room empties the off-timer still
        switches them off as normal.
        """
        switch, *_ = make_switch(
            options={"on_enter_night": "turn_off"}, day_mode=False
        )
        switch._state_ctrl.mark_controlled(["light.a"])
        fake_hass.states.set("binary_sensor.motion", FakeState(state="on"))
        fake_hass.states.set(
            "light.a",
            FakeState(state="on", attributes={"brightness": 92, "color_temp": 225}),
        )
        fake_hass.states.set("light.b", FakeState(state="off"))

        night_handler = switch._get_mode_handler(MODE_NIGHT)
        night_handler.enter(MODE_DAY)

        # Not held: the off-timer may still reach them.
        assert switch._state_ctrl.get_held_lights() == set()

        # Room empties → the off-timer collects the light and switches it off.
        fake_hass.states.set("binary_sensor.motion", FakeState(state="off"))
        lights_to_off, _ = night_handler._off_timer_result()
        assert "light.a" in lights_to_off


class TestNightToDayTransition:
    """Tests for Night→Day transition."""

    def test_clears_holds(self, make_switch, fake_hass):
        """Night→Day clears holds via the mode transition."""
        switch, *_ = make_switch(day_mode=True)
        switch._state_ctrl.set_hold(["light.a"], reason="service")

        assert switch._state_ctrl.is_held("light.a")

        # Simulate the transition: a mode change clears holds.
        switch._handle_mode_transition(MODE_NIGHT, MODE_DAY)

        assert not switch._state_ctrl.is_held("light.a")

    def test_cancels_off_timer(self, make_switch, fake_hass):
        """Night→Day cancels any running off-timer."""
        from datetime import timedelta, timezone

        switch, *_ = make_switch(day_mode=True)

        # Simulate a pending off-timer in the action scheduler
        run_at = datetime.now(timezone.utc) + timedelta(minutes=5)
        switch._action_scheduler.add(
            run_at=run_at,
            cancel_key=switch._config_entry.entry_id,
            source="MotionController",
            lights_for_log=["light.a"],
            callback_fn=lambda: (["light.a"], None),
            reason="motion_off",
        )
        assert len(switch._action_scheduler._entries) == 1

        # Get night handler and call exit (simulates transition to day)
        night_handler = switch._get_mode_handler(MODE_NIGHT)
        night_handler.exit(MODE_DAY)

        # Off-timer should have been cancelled by night handler exit
        assert len(switch._action_scheduler._entries) == 0


class TestHandleTickTransitions:
    """Tests for _handle_tick (transition detection + dispatch)."""

    def test_detects_day_to_night_transition(self, make_switch, fake_hass):
        """MODE_DAY → MODE_NIGHT transition is detected and handled."""
        switch, *_ = make_switch(
            options={"on_enter_night": "turn_off"}, day_mode=False
        )
        switch._last_mode = MODE_DAY  # was day
        # sun is below_horizon → now night

        fake_hass.services.async_call.reset_mock()

        # Mock dt_util for schedule operations
        with patch('custom_components.daynight_lighting.schedule.dt_util') as mock_dt:
            mock_dt.now.return_value = datetime(2026, 6, 15, 23, 0, 0)
            mock_dt.as_local.return_value = datetime(2026, 6, 15, 23, 0, 0)
            switch._handle_tick()

        assert switch._last_mode == MODE_NIGHT

    def test_detects_night_to_day_transition(self, make_switch, fake_hass):
        """MODE_NIGHT → MODE_DAY transition is detected and handled."""
        switch, *_ = make_switch(day_mode=True)
        switch._last_mode = MODE_NIGHT  # was night
        # sun is above_horizon → now day
        fake_hass.states.set("sensor.lux", FakeState(state="50"))

        fake_hass.services.async_call.reset_mock()

        # Mock dt_util for schedule operations
        with patch('custom_components.daynight_lighting.schedule.dt_util') as mock_dt:
            mock_dt.now.return_value = datetime(2026, 6, 15, 10, 0, 0)
            mock_dt.as_local.return_value = datetime(2026, 6, 15, 10, 0, 0)
            switch._handle_tick()

        assert switch._last_mode == MODE_DAY
