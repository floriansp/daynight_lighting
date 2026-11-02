"""A hold release must end in a defined, commanded state.

The button promises "clear the holds, reset the dials, forget the applied
values, apply the mode now". The measured failure was the opposite: releasing
in a motion-lit night without motion commanded nothing, left the pre-hold
expectation in place, and the next state report read the scene's values as a
fresh intervention — the hold was back six minutes later.

So every release takes exactly one branch, and every light it frees without
commanding keeps an expectation of what it actually shows.
"""

from __future__ import annotations

import logging
import time
from types import SimpleNamespace
import pytest

from custom_components.daynight_lighting.const import (
    MODE_DAY,
    MODE_NIGHT,
    MODE_SLEEP,
)
from custom_components.daynight_lighting.state_controller import (
    HOLD_REASON_DETECTED,
    HOLD_REASON_SERVICE,
)

from tests.conftest import (
    FakeState,
    capture_light_listener,
    light_listener,
    report_light_state,
    stub_wakeup_inactive,
)

# Scene values: what the television automated the room to.
SCENE_BRIGHTNESS = 40
SCENE_KELVIN = 3000
SCENE_ATTRS = {"brightness": 102, "color_temp_kelvin": SCENE_KELVIN}


def _pin_schedule(switch, mode: str, monkeypatch) -> None:
    """Pin the mode instead of waiting for the wall clock."""
    switch._schedule_override = SimpleNamespace(
        get_current_mode=lambda: mode,
        is_day_mode=lambda: mode == MODE_DAY,
        get_mode_and_time_for_log=lambda: ("at_time", "22:00"),
    )
    # These tests judge the release, not the ramp windows.
    stub_wakeup_inactive(monkeypatch)
    switch._last_mode = mode


@pytest.fixture
def night_switch(make_switch, monkeypatch):
    """A switch pinned to night, with a motion sensor configured.

    Returns ``(switch, handlers)``.
    """
    switch, *_ = make_switch(day_mode=False)
    _pin_schedule(switch, MODE_NIGHT, monkeypatch)
    handlers = {
        mode: switch._get_mode_handler(mode)
        for mode in (MODE_DAY, MODE_NIGHT, MODE_SLEEP)
    }
    return switch, handlers


def _day_switch(make_switch, monkeypatch):
    """A switch pinned to day, with a LUX reading that turns the lights on."""
    switch, *_ = make_switch(day_mode=True)
    _pin_schedule(switch, MODE_DAY, monkeypatch)
    switch.hass.states.set("sensor.lux", FakeState(state="5"))
    return switch


def _hold_both(switch, reason: str = HOLD_REASON_DETECTED) -> None:
    """Hold both configured lights, and show them as a scene left them."""
    for lid in switch.get_controlled_lights():
        switch.hass.states.set(lid, FakeState(state="on", attributes=dict(SCENE_ATTRS)))
    switch._state_ctrl.set_hold(switch.get_controlled_lights(), reason=reason)


def _motion(switch, present: bool) -> None:
    """Motion now / motion gone, as the motion controller would see it."""
    switch.hass.states.set(
        "binary_sensor.motion", FakeState(state="on" if present else "off")
    )


def _expected(switch, lid: str) -> dict | None:
    return switch._state_ctrl.get_expected_state(lid)


class TestReleaseNeverReholds:
    """The regression: a release must not be undone by the next light report."""

    @pytest.mark.asyncio
    async def test_release_in_dark_room_commands_off_and_does_not_re_hold(
        self, night_switch, fake_hass, monkeypatch
    ):
        """Night, no motion, nobody moves after the television goes off.

        The old code left this to the off timer and could end up commanding
        nothing at all. Now the release switches the released lights off, and
        the report that follows matches what we commanded.
        """
        switch, _ = night_switch
        _motion(switch, present=False)
        _hold_both(switch)
        captured = capture_light_listener(monkeypatch)
        switch._start_listeners()
        listener = light_listener(captured)

        switch.release_hold()

        for lid in switch.get_controlled_lights():
            expected = _expected(switch, lid)
            assert expected is not None, "a release must not leave a light unrecorded"
            assert expected["on"] is False

        # The lights follow our OFF; nothing here may read that as an
        # intervention. The grace period is dropped so this really tests the
        # expectation and not the shield around our own command.
        switch._manual_control_detector._last_applied_time.clear()
        for lid in switch.get_controlled_lights():
            state = FakeState(state="off")
            fake_hass.states.set(lid, state)
            report_light_state(listener, lid, state)

        assert switch._state_ctrl.get_held_lights() == set()

    @pytest.mark.asyncio
    async def test_no_expectation_survives_older_than_the_release(
        self, night_switch, monkeypatch
    ):
        """Whatever the branch, no released light keeps the pre-release idea."""
        switch, _ = night_switch
        _motion(switch, present=False)
        _hold_both(switch)
        # The scene left its own expectation behind, hours ago.
        for lid in switch.get_controlled_lights():
            switch._state_ctrl.set_expected_state(
                lid, on=True, brightness_pct=SCENE_BRIGHTNESS, kelvin=SCENE_KELVIN
            )
            switch._state_ctrl._expected_states[lid]["timestamp"] = time.time() - 3600

        started = time.time()
        switch.release_hold()

        for lid in switch.get_controlled_lights():
            expected = _expected(switch, lid)
            assert expected is not None
            assert expected["timestamp"] >= started


class TestReleaseBranches:
    """One branch per release moment, each logged with what it commanded."""

    @pytest.mark.asyncio
    async def test_night_without_motion_turns_the_off_timer_selection_off(
        self, night_switch, caplog
    ):
        switch, _ = night_switch
        _motion(switch, present=False)
        _hold_both(switch)

        with caplog.at_level(logging.INFO, logger="custom_components.daynight_lighting.switch"):
            switch.release_hold()

        lights = switch.get_controlled_lights()
        for lid in lights:
            assert _expected(switch, lid)["on"] is False
            # The applier released the lights it switched off.
            assert not switch._state_ctrl.is_controlled_by_us(lid)
        assert "branch=night-off" in caplog.text
        assert f"commanded={len(lights)}" in caplog.text
        assert "adopted=0" in caplog.text

    @pytest.mark.asyncio
    async def test_night_without_motion_adopts_when_nothing_is_selected(
        self, night_switch, monkeypatch
    ):
        """The off timer selects nothing: record the truth instead of nothing."""
        switch, handlers = night_switch
        _motion(switch, present=False)
        _hold_both(switch)
        monkeypatch.setattr(
            handlers[MODE_NIGHT],
            "_off_timer_result",
            lambda: ([], "no lights to turn off"),
        )
        monkeypatch.setattr(
            handlers[MODE_NIGHT],
            "_turn_off_lights",
            lambda lights: pytest.fail("nothing was selected, nothing to switch off"),
        )

        switch.release_hold()

        for lid in switch.get_controlled_lights():
            expected = _expected(switch, lid)
            assert expected is not None
            # Adopted: on, with the brightness the lamp actually reports.
            assert expected["on"] is True
            assert expected["brightness_pct"] == round(102 / 255 * 100)
            # And shielded from being read back as a change we did not make.
            assert switch._manual_control_detector.is_in_grace_period(lid) is True

    @pytest.mark.asyncio
    async def test_adopted_light_does_not_re_hold_on_its_next_report(
        self, night_switch, fake_hass, monkeypatch
    ):
        """The adopted scene values are the expectation, so no intervention."""
        switch, _ = night_switch
        _motion(switch, present=False)
        _hold_both(switch)
        captured = capture_light_listener(monkeypatch)
        # Subscribing rebuilds the handlers from the options, so the branch is
        # stubbed on the fresh handler, after the listeners exist.
        switch._start_listeners()
        night = switch._get_mode_handler(MODE_NIGHT)
        monkeypatch.setattr(night, "_off_timer_result", lambda: ([], "none"))
        listener = light_listener(captured)

        switch.release_hold()
        switch._first_tick_after_startup = False
        switch._manual_control_detector._last_applied_time.clear()

        # The lamp confirms the values it already had.
        for lid in switch.get_controlled_lights():
            state = FakeState(state="on", attributes=dict(SCENE_ATTRS))
            fake_hass.states.set(lid, state)
            report_light_state(listener, lid, state)

        assert switch._state_ctrl.get_held_lights() == set()

    @pytest.mark.asyncio
    async def test_night_with_motion_hands_the_room_back(self, night_switch):
        """Motion is present: the released lights become ours again and are
        re-applied to the night target."""
        switch, handlers = night_switch
        _motion(switch, present=True)
        _hold_both(switch)

        switch.release_hold()

        night_brightness = handlers[MODE_NIGHT].get_brightness_pct()
        assert night_brightness != SCENE_BRIGHTNESS
        for lid in switch.get_controlled_lights():
            # Marked controlled before the apply: otherwise the motion apply
            # aborts the whole room and commands nothing.
            assert switch._state_ctrl.is_controlled_by_us(lid)
            expected = _expected(switch, lid)
            assert expected is not None
            assert expected["on"] is True
            assert expected["brightness_pct"] == night_brightness

    @pytest.mark.asyncio
    async def test_day_mode_applies_the_mode(self, make_switch, monkeypatch):
        switch = _day_switch(make_switch, monkeypatch)
        _hold_both(switch)

        switch.release_hold()

        for lid in switch.get_controlled_lights():
            assert _expected(switch, lid) is not None
        assert switch._state_ctrl.get_held_lights() == set()

    @pytest.mark.asyncio
    async def test_service_ramp_is_left_alone(self, night_switch, monkeypatch, caplog):
        """A service-started sleep owns the values; the release must not
        fight it, but must still record what the lights look like."""
        switch, handlers = night_switch
        sleep = handlers[MODE_SLEEP]
        monkeypatch.setattr(sleep, "is_sleep_active", lambda: True)
        # The ramp is the only one allowed to drive the lights; here it has
        # nothing to send, which is exactly the "commands nothing" case.
        monkeypatch.setattr(sleep, "tick", lambda: None)
        night = handlers[MODE_NIGHT]
        monkeypatch.setattr(night, "reapply_after_release", lambda: pytest.fail(
            "the night apply must not run during a service ramp"
        ))
        monkeypatch.setattr(night, "_off_timer_result", lambda: pytest.fail(
            "the off timer must not run during a service ramp"
        ))
        _hold_both(switch)

        with caplog.at_level(logging.INFO, logger="custom_components.daynight_lighting.switch"):
            switch.release_hold()

        assert "branch=service-ramp" in caplog.text
        assert "commanded=0" in caplog.text
        # Nothing was commanded, so the state is adopted instead of assumed.
        assert f"adopted={len(switch.get_controlled_lights())}" in caplog.text


class TestGenuineDivergenceStillHolds:
    """A light that ignores our OFF is a real divergence, not a bug."""

    @pytest.mark.asyncio
    async def test_lamp_ignoring_the_off_is_held_again(
        self, night_switch, fake_hass, monkeypatch, caplog
    ):
        switch, _ = night_switch
        _motion(switch, present=False)
        _hold_both(switch)
        captured = capture_light_listener(monkeypatch)
        switch._start_listeners()
        listener = light_listener(captured)

        with caplog.at_level(logging.INFO, logger="custom_components.daynight_lighting.switch"):
            switch.release_hold()
        assert "branch=night-off" in caplog.text

        switch._first_tick_after_startup = False
        # The lamp stays on at the scene's values although we said OFF.
        for lid in switch.get_controlled_lights():
            state = FakeState(state="on", attributes=dict(SCENE_ATTRS))
            fake_hass.states.set(lid, state)
            switch._manual_control_detector._last_applied_time.clear()
            report_light_state(listener, lid, state)

        assert switch._state_ctrl.get_held_lights() == set(switch.get_controlled_lights())
        for lid in switch.get_controlled_lights():
            assert switch._state_ctrl.get_hold_reason(lid) == HOLD_REASON_DETECTED


class TestServiceHoldsReleaseTheSameWay:
    """The reason of the hold does not change how it ends."""

    @pytest.mark.asyncio
    async def test_service_hold_ends_in_the_same_defined_state(
        self, make_switch, monkeypatch, caplog
    ):
        switch = _day_switch(make_switch, monkeypatch)
        _hold_both(switch, reason=HOLD_REASON_SERVICE)

        with caplog.at_level(logging.INFO, logger="custom_components.daynight_lighting.switch"):
            switch.release_hold()

        assert switch._state_ctrl.get_held_lights() == set()
        assert "branch=mode-apply" in caplog.text
        for lid in switch.get_controlled_lights():
            assert _expected(switch, lid) is not None


class TestReleaseLog:
    """The log names the branch and the counts, so the next case is readable."""

    @pytest.mark.asyncio
    async def test_log_line_names_branch_and_counts(
        self, night_switch, monkeypatch, caplog
    ):
        switch, handlers = night_switch
        _motion(switch, present=False)
        _hold_both(switch)
        # One light is commanded off, the other is not selected at all.
        leds = switch.get_controlled_lights()
        monkeypatch.setattr(
            switch, "_get_mode_handler", lambda mode: handlers.get(mode)
        )
        monkeypatch.setattr(
            handlers[MODE_NIGHT], "_off_timer_result", lambda: ([leds[0]], None)
        )

        with caplog.at_level(logging.INFO, logger="custom_components.daynight_lighting.switch"):
            switch.release_hold()

        released = caplog.text
        assert f"hold released: {len(leds)} light(s)" in released
        assert "branch=night-off" in released
        assert "commanded=1" in released
        assert f"adopted={len(leds) - 1}" in released
