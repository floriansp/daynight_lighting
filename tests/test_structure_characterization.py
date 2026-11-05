"""Characterisation tests for the structural clean-up of handlers and switch.

They pin what a resident (or the light service) can observe around code that a
pure restructuring touches: which transition context each switch-off uses, how
a hold release leaves a pending off timer alone, which reason a service hold
carries, what the transition coordinator commands after a ramp, and how every
mode handler honours Control Brightness / Control Colour.
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from custom_components.daynight_lighting.const import (
    CONF_INITIAL_TRANSITION_SECONDS,
    CONF_MODE_TRANSITION_SECONDS,
    CONF_SLEEP_DURATION_MIN,
    CONF_SLEEP_ENABLED,
    CONF_SLEEP_START_TIME,
    CONF_TRANSITION_SECONDS,
    MODE_DAY,
    MODE_NIGHT,
    MODE_SLEEP,
    MODE_WAKEUP,
)
from custom_components.daynight_lighting.handlers.base import ModeHandler
from custom_components.daynight_lighting.manual_control import ExpectedState
from custom_components.daynight_lighting.transition_coordinator import (
    TransitionCoordinator,
)

from tests.conftest import FakeState, stub_wakeup_inactive

# Three distinct values, so a wrong context shows up as a wrong number.
TICK_S = 20
INITIAL_S = 60
MODE_S = 40
TRANSITIONS = {
    CONF_TRANSITION_SECONDS: TICK_S,
    CONF_INITIAL_TRANSITION_SECONDS: INITIAL_S,
    CONF_MODE_TRANSITION_SECONDS: MODE_S,
}


def _payloads(fake_hass, service: str) -> list[dict]:
    """Payloads of the light service calls of one kind, in order."""
    return [
        call[0][2]
        for call in fake_hass.services.async_call.call_args_list
        if call[0][1] == service
    ]


# ===================================================================
#  Which transition a switch-off uses
# ===================================================================


class TestSwitchOffTransitionContext:
    """Every off command carries the transition of its own context."""

    def test_day_lux_off_uses_the_tick_transition(self, make_switch, fake_hass):
        switch, *_ = make_switch(
            {
                **TRANSITIONS,
                "day_min_brightness": 0,
                "lux_off": 55,
                "day_max_brightness": 45,
            },
            day_mode=True,
        )
        fake_hass.states.set("sensor.lux", FakeState(state="80"))

        switch._get_mode_handler(MODE_DAY).tick()

        assert _payloads(fake_hass, "turn_off") == [
            {"entity_id": ["light.a", "light.b"], "transition": TICK_S}
        ]

    def test_day_fallback_off_uses_the_tick_transition(self, make_switch, fake_hass):
        switch, *_ = make_switch(
            {**TRANSITIONS, "light_sensor": None, "day_mode_fallback": "off"},
            day_mode=True,
        )

        switch._get_mode_handler(MODE_DAY).tick()

        assert _payloads(fake_hass, "turn_off") == [
            {"entity_id": ["light.a", "light.b"], "transition": TICK_S}
        ]

    def test_night_fallback_off_uses_the_tick_transition(self, make_switch, fake_hass):
        switch, *_ = make_switch(
            {**TRANSITIONS, "motion_sensor": None, "night_mode_fallback": "off"},
            day_mode=False,
        )

        switch._get_mode_handler(MODE_NIGHT).tick()

        assert _payloads(fake_hass, "turn_off") == [
            {"entity_id": ["light.a", "light.b"], "transition": TICK_S}
        ]

    def test_entering_night_with_turn_off_uses_the_tick_transition(
        self, make_switch, fake_hass
    ):
        switch, *_ = make_switch(
            {**TRANSITIONS, "on_enter_night": "turn_off"}, day_mode=False
        )
        fake_hass.states.set("binary_sensor.motion", FakeState(state="off"))

        switch._get_mode_handler(MODE_NIGHT).enter(MODE_DAY)

        assert _payloads(fake_hass, "turn_off") == [
            {"entity_id": ["light.a", "light.b"], "transition": TICK_S}
        ]

    def test_sleep_end_uses_the_mode_transition(self, make_switch, fake_hass):
        switch, *_ = make_switch(
            {
                **TRANSITIONS,
                "lights": ["light.a"],
                CONF_SLEEP_ENABLED: True,
                CONF_SLEEP_START_TIME: "21:00",
                CONF_SLEEP_DURATION_MIN: 60,
            },
            day_mode=True,
        )
        sleep = switch._get_mode_handler(MODE_SLEEP)
        sleep._sleep_active = True
        sleep._sleep_start_time = datetime(2026, 6, 15, 21, 0, 0)

        with patch("custom_components.daynight_lighting.handlers.sleep.dt_util") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 6, 15, 22, 30, 0)
            sleep.tick()

        assert _payloads(fake_hass, "turn_off") == [
            {"entity_id": ["light.a"], "transition": MODE_S}
        ]


# ===================================================================
#  Release in a motion-lit night without motion
# ===================================================================


def _pin_night(switch, monkeypatch) -> None:
    """Pin the schedule to night instead of waiting for the wall clock."""
    switch._schedule_override = SimpleNamespace(
        get_current_mode=lambda: MODE_NIGHT,
        is_day_mode=lambda: False,
        get_mode_and_time_for_log=lambda: ("at_time", "22:00"),
    )
    stub_wakeup_inactive(monkeypatch)
    switch._last_mode = MODE_NIGHT


def _hold_both_on(switch, fake_hass) -> None:
    for lid in ("light.a", "light.b"):
        fake_hass.states.set(lid, FakeState(state="on", attributes={"brightness": 102}))
    switch._state_ctrl.set_hold(["light.a", "light.b"], reason="detected")


class TestReleaseNightOff:
    """The release switches the room off exactly like the off timer would."""

    def test_off_command_uses_the_tick_transition(
        self, make_switch, fake_hass, monkeypatch
    ):
        switch, *_ = make_switch(TRANSITIONS, day_mode=False)
        _pin_night(switch, monkeypatch)
        fake_hass.states.set("binary_sensor.motion", FakeState(state="off"))
        _hold_both_on(switch, fake_hass)

        switch.release_hold()

        assert _payloads(fake_hass, "turn_off") == [
            {"entity_id": ["light.a", "light.b"], "transition": TICK_S}
        ]
        assert _payloads(fake_hass, "turn_on") == []

    def test_a_pending_off_timer_is_left_running(
        self, make_switch, fake_hass, monkeypatch
    ):
        """The release does not touch the timer; only motion or a service does."""
        switch, *_ = make_switch(day_mode=False)
        _pin_night(switch, monkeypatch)
        fake_hass.states.set("binary_sensor.motion", FakeState(state="off"))
        switch._state_ctrl.mark_controlled(["light.a", "light.b"])
        switch._handle_motion_off()
        assert len(switch._action_scheduler._entries) == 1
        _hold_both_on(switch, fake_hass)

        switch.release_hold()

        assert len(switch._action_scheduler._entries) == 1

    def test_released_lights_are_no_longer_controlled(
        self, make_switch, fake_hass, monkeypatch
    ):
        switch, *_ = make_switch(day_mode=False)
        _pin_night(switch, monkeypatch)
        fake_hass.states.set("binary_sensor.motion", FakeState(state="off"))
        switch._state_ctrl.mark_controlled(["light.a", "light.b"])
        _hold_both_on(switch, fake_hass)

        switch.release_hold()

        assert not switch._state_ctrl.is_controlled_by_us("light.a")
        assert not switch._state_ctrl.is_controlled_by_us("light.b")
        assert switch._state_ctrl.get_held_lights() == set()


# ===================================================================
#  Hold reasons set by the services
# ===================================================================


class TestServiceHoldReason:
    """A visitor's turn_on / turn_off is held with the reason 'service'."""

    def test_turn_on_hold_reason(self, make_switch):
        switch, *_ = make_switch(day_mode=False)

        switch.record_lights_turned_on_by_service(["light.a"])

        assert switch._state_ctrl.get_hold_reason("light.a") == "service"

    def test_turn_off_hold_reason(self, make_switch):
        switch, *_ = make_switch(day_mode=False)

        switch.record_lights_turned_off_by_service(["light.a"])

        assert switch._state_ctrl.get_hold_reason("light.a") == "service"

    def test_service_holds_end_at_the_phase_change_detected_ones_stay(
        self, make_switch
    ):
        switch, *_ = make_switch(day_mode=False)
        switch.record_lights_turned_on_by_service(["light.a"])
        switch._state_ctrl.set_hold(["light.b"], reason="detected")

        switch._handle_mode_transition(MODE_DAY, MODE_NIGHT)

        assert switch._state_ctrl.get_held_lights_with_reasons() == {
            "light.b": "detected"
        }


# ===================================================================
#  What the coordinator commands after a ramp
# ===================================================================


def _coordinator(fake_hass, expected: ExpectedState, *, brightness_on=True, color_on=True):
    """A coordinator whose day and night handlers both expect *expected*."""
    handlers = {}
    for mode in (MODE_DAY, MODE_NIGHT):
        handler = MagicMock()
        handler.calculate_expected_state.return_value = expected
        handlers[mode] = handler

    lights = MagicMock()
    lights.get_lights_list.return_value = ["light.a", "light.b"]
    state_ctrl = MagicMock()
    applied: list[ExpectedState] = []

    coordinator = TransitionCoordinator(
        hass=fake_hass,
        instance_name="Test",
        handlers=handlers,
        lights=lights,
        motion=MagicMock(),
        state_ctrl=state_ctrl,
        get_transition=lambda ctx: {"tick": TICK_S, "initial": INITIAL_S, "mode": MODE_S}[ctx],
        is_control_brightness_on=lambda: brightness_on,
        is_control_color_on=lambda: color_on,
        on_applied=applied.append,
    )
    return coordinator, state_ctrl, applied


class TestCoordinatorAfterRamp:
    """The wake-up hands over by applying what the target mode expects."""

    @pytest.mark.parametrize(
        "from_mode, to_mode",
        [(MODE_WAKEUP, MODE_DAY), (MODE_WAKEUP, MODE_NIGHT)],
    )
    def test_on_expected_commands_brightness_and_colour(
        self, fake_hass, from_mode, to_mode
    ):
        coordinator, state_ctrl, applied = _coordinator(
            fake_hass, ExpectedState(on=True, brightness_pct=70, kelvin=3000)
        )

        coordinator.transition_sync(from_mode, to_mode)

        assert _payloads(fake_hass, "turn_on") == [
            {
                "entity_id": ["light.a", "light.b"],
                "brightness_pct": 70,
                "color_temp_kelvin": 3000,
                "transition": MODE_S,
            }
        ]
        state_ctrl.set_expected_state.assert_any_call(
            "light.a", on=True, brightness_pct=70, kelvin=3000
        )
        assert applied == [ExpectedState(on=True, brightness_pct=70, kelvin=3000)]

    def test_off_expected_turns_the_lights_off(self, fake_hass):
        coordinator, state_ctrl, _ = _coordinator(fake_hass, ExpectedState(on=False))

        coordinator.transition_sync(MODE_WAKEUP, MODE_DAY)

        assert _payloads(fake_hass, "turn_off") == [
            {"entity_id": ["light.a", "light.b"], "transition": MODE_S}
        ]
        assert _payloads(fake_hass, "turn_on") == []
        state_ctrl.set_expected_state.assert_any_call("light.a", on=False)

    def test_brightness_control_off_leaves_brightness_out(self, fake_hass):
        coordinator, state_ctrl, _ = _coordinator(
            fake_hass,
            ExpectedState(on=True, brightness_pct=70, kelvin=3000),
            brightness_on=False,
        )

        coordinator.transition_sync(MODE_WAKEUP, MODE_DAY)

        assert _payloads(fake_hass, "turn_on") == [
            {
                "entity_id": ["light.a", "light.b"],
                "color_temp_kelvin": 3000,
                "transition": MODE_S,
            }
        ]
        state_ctrl.set_expected_state.assert_any_call(
            "light.a", on=True, brightness_pct=None, kelvin=3000
        )

    def test_colour_control_off_leaves_colour_out(self, fake_hass):
        coordinator, state_ctrl, _ = _coordinator(
            fake_hass,
            ExpectedState(on=True, brightness_pct=70, kelvin=3000),
            color_on=False,
        )

        coordinator.transition_sync(MODE_WAKEUP, MODE_NIGHT)

        assert _payloads(fake_hass, "turn_on") == [
            {
                "entity_id": ["light.a", "light.b"],
                "brightness_pct": 70,
                "transition": MODE_S,
            }
        ]
        state_ctrl.set_expected_state.assert_any_call(
            "light.a", on=True, brightness_pct=70, kelvin=None
        )

    def test_nothing_to_command_sends_nothing(self, fake_hass):
        coordinator, _, applied = _coordinator(
            fake_hass,
            ExpectedState(on=True, brightness_pct=70, kelvin=3000),
            brightness_on=False,
            color_on=False,
        )

        coordinator.transition_sync(MODE_WAKEUP, MODE_DAY)

        fake_hass.services.async_call.assert_not_called()
        assert applied == []

    def test_expected_without_values_sends_nothing(self, fake_hass):
        coordinator, _, _ = _coordinator(fake_hass, ExpectedState(on=True))

        coordinator.transition_sync(MODE_WAKEUP, MODE_DAY)

        fake_hass.services.async_call.assert_not_called()

    @pytest.mark.parametrize(
        "from_mode, to_mode",
        [
            (MODE_NIGHT, MODE_DAY),
            (MODE_DAY, MODE_SLEEP),
            (MODE_SLEEP, MODE_NIGHT),
            (MODE_NIGHT, MODE_WAKEUP),
        ],
    )
    def test_other_transitions_command_nothing_themselves(
        self, fake_hass, from_mode, to_mode
    ):
        coordinator, _, _ = _coordinator(
            fake_hass, ExpectedState(on=True, brightness_pct=70, kelvin=3000)
        )

        coordinator.transition_sync(from_mode, to_mode)

        fake_hass.services.async_call.assert_not_called()

    def test_target_mode_without_handler_sends_nothing(self, fake_hass):
        coordinator, _, _ = _coordinator(
            fake_hass, ExpectedState(on=True, brightness_pct=70, kelvin=3000)
        )
        del coordinator._handlers[MODE_DAY]

        coordinator.transition_sync(MODE_WAKEUP, MODE_DAY)

        fake_hass.services.async_call.assert_not_called()


# ===================================================================
#  What every mode handler offers and honours
# ===================================================================


@pytest.fixture
def handlers(make_switch):
    """The four mode handlers of one switch, with the two control toggles."""
    switch, ctrl_brightness, ctrl_color = make_switch(day_mode=True)
    by_mode = {
        mode: switch._get_mode_handler(mode)
        for mode in (MODE_DAY, MODE_NIGHT, MODE_SLEEP, MODE_WAKEUP)
    }
    return by_mode, ctrl_brightness, ctrl_color


class TestHandlerSurface:
    """All four handlers satisfy the one handler protocol."""

    @pytest.mark.parametrize("mode", [MODE_DAY, MODE_NIGHT, MODE_SLEEP, MODE_WAKEUP])
    def test_handler_implements_the_protocol(self, handlers, mode):
        by_mode, *_ = handlers

        assert isinstance(by_mode[mode], ModeHandler)


class TestHandlersHonourTheControlSwitches:
    """Control Brightness / Control Colour decide what a payload carries."""

    @pytest.mark.parametrize("mode", [MODE_DAY, MODE_SLEEP, MODE_WAKEUP])
    def test_both_on_carry_both(self, handlers, mode):
        by_mode, *_ = handlers

        payload = by_mode[mode].build_light_payload(["light.a"], 50, 3000)

        assert payload == {
            "entity_id": ["light.a"],
            "brightness_pct": 50,
            "color_temp_kelvin": 3000,
        }

    @pytest.mark.parametrize("mode", [MODE_DAY, MODE_SLEEP, MODE_WAKEUP])
    def test_brightness_off_leaves_brightness_out(self, handlers, mode):
        by_mode, ctrl_brightness, _ = handlers
        ctrl_brightness._attr_is_on = False

        payload = by_mode[mode].build_light_payload(["light.a"], 50, 3000)

        assert payload == {"entity_id": ["light.a"], "color_temp_kelvin": 3000}

    @pytest.mark.parametrize("mode", [MODE_DAY, MODE_SLEEP, MODE_WAKEUP])
    def test_colour_off_leaves_colour_out(self, handlers, mode):
        by_mode, _, ctrl_color = handlers
        ctrl_color._attr_is_on = False

        payload = by_mode[mode].build_light_payload(["light.a"], 50, 3000)

        assert payload == {"entity_id": ["light.a"], "brightness_pct": 50}

    @pytest.mark.parametrize("mode", [MODE_DAY, MODE_SLEEP, MODE_WAKEUP])
    def test_both_off_carry_nothing(self, handlers, mode):
        by_mode, ctrl_brightness, ctrl_color = handlers
        ctrl_brightness._attr_is_on = False
        ctrl_color._attr_is_on = False

        assert by_mode[mode].build_light_payload(["light.a"], 50, 3000) is None

    def test_night_both_off_carries_only_the_lights(self, handlers):
        by_mode, ctrl_brightness, ctrl_color = handlers
        ctrl_brightness._attr_is_on = False
        ctrl_color._attr_is_on = False

        payload = by_mode[MODE_NIGHT].build_light_payload(["light.a"])

        assert payload == {"entity_id": ["light.a"]}

    def test_night_expected_state_follows_the_switches(self, make_switch, fake_hass):
        switch, ctrl_brightness, ctrl_color = make_switch(day_mode=False)
        fake_hass.states.set("binary_sensor.motion", FakeState(state="on"))
        night = switch._get_mode_handler(MODE_NIGHT)

        full = night.calculate_expected_state()
        assert full.on is True
        assert full.brightness_pct == 80
        assert full.kelvin is not None

        ctrl_brightness._attr_is_on = False
        ctrl_color._attr_is_on = False
        bare = night.calculate_expected_state()
        assert bare == ExpectedState(on=True, brightness_pct=None, kelvin=None)
