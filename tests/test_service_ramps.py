"""Functional tests: a sleep or wake-up started by service.

Such a ramp drives the lights although the schedule never entered the mode, so
it must show as the room's mode, and it must carry through the phase changes
the clock makes while it runs.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from custom_components.daynight_lighting.const import (
    MODE_DAY,
    MODE_NIGHT,
    MODE_SLEEP,
    MODE_WAKEUP,
)

from tests.conftest import FakeState

_SCHEDULE_CLOCK = "custom_components.daynight_lighting.mode_schedule.dt_util"


@pytest.fixture
def night_switch(make_switch):
    """An instance in a dark phase, as the wake-up service finds it at dawn."""
    switch, *_ = make_switch(day_mode=False)
    switch._last_mode = MODE_NIGHT
    switch.notify_monitors = MagicMock()
    return switch


def _sunrise(fake_hass) -> None:
    fake_hass.states.set(
        "sun.sun",
        FakeState(
            state="above_horizon",
            attributes={"elevation": 1.0, "next_rising": "2026-06-16T05:15:00+00:00"},
        ),
    )


def _tick(switch) -> None:
    with patch(_SCHEDULE_CLOCK) as clock:
        clock.now.return_value = datetime(2026, 6, 15, 7, 0, 0)
        clock.as_local.return_value = datetime(2026, 6, 15, 7, 0, 0)
        switch._handle_tick()


class TestRampIsTheReportedMode:
    """Sensors mirror what drives the lights, not what the clock would say."""

    def test_wakeup_by_service(self, night_switch):
        night_switch.start_wakeup_mode_now(duration_min=10)

        assert night_switch.get_active_mode() == MODE_WAKEUP
        assert night_switch.get_mode_progress() is not None

    def test_sleep_by_service(self, night_switch):
        night_switch.start_sleep_mode_now(duration_min=30)

        assert night_switch.get_active_mode() == MODE_SLEEP
        assert night_switch.get_mode_progress() is not None

    def test_the_schedules_mode_is_left_alone(self, night_switch):
        """The ramp is a view, not a transition: the schedule's side stays."""
        night_switch.start_wakeup_mode_now(duration_min=10)

        assert night_switch._last_mode == MODE_NIGHT

    def test_the_mode_returns_when_the_ramp_is_stopped(self, night_switch):
        night_switch.start_wakeup_mode_now(duration_min=10)

        night_switch.stop_wakeup_mode_now()

        assert night_switch.get_active_mode() == MODE_NIGHT
        assert night_switch.get_mode_progress() is None

    def test_an_instance_that_is_off_reports_no_mode(self, night_switch):
        night_switch.start_wakeup_mode_now(duration_min=10)
        night_switch._last_mode = None

        assert night_switch.get_active_mode() is None

    @pytest.mark.parametrize(
        "action",
        [
            lambda s: s.start_wakeup_mode_now(duration_min=10),
            lambda s: s.start_sleep_mode_now(duration_min=30),
            lambda s: s.stop_wakeup_mode_now(),
            lambda s: s.stop_sleep_mode_now(),
        ],
        ids=["start-wakeup", "start-sleep", "stop-wakeup", "stop-sleep"],
    )
    def test_starting_and_stopping_tell_the_sensors(self, night_switch, action):
        """Not left to the next minute tick, and not to an applied light."""
        action(night_switch)

        night_switch.notify_monitors.assert_called()


class TestRampStartEndsEveryHold:
    """An alarm or a bedtime is asked for, so no evening hold may block it."""

    @staticmethod
    def _hold_both(switch) -> None:
        switch._state_ctrl.set_hold(["light.a"], reason="detected")
        switch._state_ctrl.set_hold(["light.b"], reason="service")

    @pytest.mark.parametrize(
        "start",
        [
            lambda s: s.start_wakeup_mode_now(duration_min=10),
            lambda s: s.start_sleep_mode_now(duration_min=30),
        ],
        ids=["wakeup", "sleep"],
    )
    def test_service_start_ends_service_and_detected_holds(self, night_switch, start):
        self._hold_both(night_switch)

        start(night_switch)

        assert night_switch._state_ctrl.get_held_lights() == set()

    @pytest.mark.parametrize("ramp", [MODE_WAKEUP, MODE_SLEEP])
    def test_the_clock_entering_a_ramp_ends_every_hold(self, night_switch, ramp):
        self._hold_both(night_switch)

        night_switch._handle_mode_transition(MODE_NIGHT, ramp)

        assert night_switch._state_ctrl.get_held_lights() == set()

    def test_the_lights_are_reached_by_the_wakeup(self, night_switch, fake_hass):
        self._hold_both(night_switch)
        fake_hass.services.async_call.reset_mock()

        night_switch.start_wakeup_mode_now(duration_min=10)

        lit = [
            light
            for call in fake_hass.services.async_call.call_args_list
            if call[0][1] == "turn_on"
            for light in call[0][2]["entity_id"]
        ]
        assert set(lit) == {"light.a", "light.b"}

    def test_a_plain_phase_change_still_keeps_a_detected_hold(self, night_switch):
        self._hold_both(night_switch)

        night_switch._handle_mode_transition(MODE_NIGHT, MODE_DAY)

        assert night_switch._state_ctrl.get_held_lights() == {"light.a"}


class TestRampThroughSunrise:
    """A wake-up begun in the night is not cut short by the day arriving."""

    def test_the_ramp_runs_on_and_the_day_follows_it(self, night_switch, fake_hass):
        wakeup = night_switch._get_mode_handler(MODE_WAKEUP)
        night_switch.start_wakeup_mode_now(duration_min=10)

        _sunrise(fake_hass)  # the clock turns to day halfway through
        _tick(night_switch)

        assert wakeup.is_service_triggered_active()
        assert night_switch.get_active_mode() == MODE_WAKEUP
        assert night_switch._last_mode == MODE_NIGHT, "no transition mid-ramp"

        wakeup._wakeup_start_time -= timedelta(minutes=11)  # the ramp runs out
        _tick(night_switch)

        assert not wakeup.is_service_triggered_active()

        _tick(night_switch)

        assert night_switch._last_mode == MODE_DAY
        assert night_switch.get_active_mode() == MODE_DAY
