"""Tests for the phase-bound hold set by turn_on/turn_off.

A visitor's wall button press reaches us as ``daynight_lighting.turn_on`` /
``turn_off``. Those services hold the lights in place until the phase ends,
so the day/night automation does not immediately undo the visitor's choice.
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

from homeassistant.util import dt as dt_util

from custom_components.daynight_lighting.const import DOMAIN, MODE_DAY, MODE_NIGHT
from custom_components.daynight_lighting.context import SharedHandlerDeps
from custom_components.daynight_lighting.handlers import (
    SleepModeHandler,
    WakeUpModeHandler,
)
from custom_components.daynight_lighting.instance_data import KEY_NIGHT_BRIGHTNESS
from custom_components.daynight_lighting.number import DayNightNightBrightnessNumber

from tests.conftest import FakeState


def _handler_shared(fake_hass, held):
    """SharedHandlerDeps with two lights and *held* marked as held."""
    mocks = {
        "state_ctrl": MagicMock(),
        "circadian": MagicMock(),
        "lights": MagicMock(),
    }
    mocks["state_ctrl"].mark_controlled = MagicMock()
    mocks["circadian"].is_enabled.return_value = True
    mocks["circadian"].get_kelvin.return_value = (4000, 30.0)
    mocks["lights"].get_lights_list.return_value = ["light.a", "light.b"]

    shared = SharedHandlerDeps(
        hass=fake_hass,
        instance_name="Test",
        lights=mocks["lights"],
        state_ctrl=mocks["state_ctrl"],
        is_control_brightness_on=lambda: True,
        is_control_color_on=lambda: True,
        get_transition=lambda ctx: 0,
        get_held_lights=lambda: set(held),
    )
    return shared, mocks


def _light_entities(fake_hass, service="turn_on"):
    """Entity ids a light service call was made for, in order."""
    result = []
    for call in fake_hass.services.async_call.call_args_list:
        if call[0][:2] == ("light", service):
            payload = call[0][2]
            entity = payload.get("entity_id")
            if isinstance(entity, list):
                result.extend(entity)
            elif entity:
                result.append(entity)
    return result


class TestHoldIsSetByServices:
    """turn_on and turn_off hold the lights they were called for."""

    def test_turn_on_holds(self, make_switch, fake_hass):
        switch, *_ = make_switch()
        switch.record_lights_turned_on_by_service(["light.a", "light.b"])
        assert switch._state_ctrl.is_held("light.a")
        assert switch._state_ctrl.is_held("light.b")

    def test_turn_off_holds(self, make_switch, fake_hass):
        switch, *_ = make_switch()
        switch.record_lights_turned_off_by_service(["light.a"])
        assert switch._state_ctrl.is_held("light.a")


class TestHoldSkipsAutomatics:
    """The mode handlers leave held lights alone."""

    def test_day_handler_skips_held_light(self, make_switch, fake_hass):
        switch, *_ = make_switch({}, day_mode=True)
        fake_hass.states.set("sensor.lux", FakeState(state="55"))
        fake_hass.states.set("light.a", FakeState(state="off"))
        fake_hass.states.set("light.b", FakeState(state="off"))
        switch._state_ctrl.set_hold(["light.a"])

        switch._get_mode_handler(MODE_DAY).tick()

        assert "light.a" not in _light_entities(fake_hass)
        assert "light.b" in _light_entities(fake_hass)

    def test_night_motion_skips_held_light(self, make_switch, fake_hass):
        switch, *_ = make_switch({}, day_mode=False)
        fake_hass.states.set("binary_sensor.motion", FakeState(state="on"))
        fake_hass.states.set("light.a", FakeState(state="off"))
        fake_hass.states.set("light.b", FakeState(state="off"))
        switch._state_ctrl.set_hold(["light.a"])

        switch._get_mode_handler(MODE_NIGHT).handle_motion_on()

        assert "light.a" not in _light_entities(fake_hass)
        assert "light.b" in _light_entities(fake_hass)

    def test_night_off_timer_skips_held_light(self, make_switch, fake_hass):
        switch, *_ = make_switch({}, day_mode=False)
        switch._state_ctrl.mark_controlled(["light.a", "light.b"])
        switch._state_ctrl.set_hold(["light.a"])
        fake_hass.states.set("binary_sensor.motion", FakeState(state="off"))

        result, _ = switch._get_mode_handler(MODE_NIGHT)._off_timer_result()

        assert result == ["light.b"]

    def test_night_enter_turn_off_excludes_held(self, make_switch, fake_hass):
        """Entering night with turn_off leaves a held (visitor) light alone."""
        switch, *_ = make_switch({"on_enter_night": "turn_off"}, day_mode=False)
        fake_hass.states.set("light.a", FakeState(state="on"))
        fake_hass.states.set("light.b", FakeState(state="on"))
        switch._state_ctrl.set_hold(["light.a"])

        switch._get_mode_handler(MODE_NIGHT).enter(None)

        assert "light.a" not in _light_entities(fake_hass, "turn_off")
        assert "light.b" in _light_entities(fake_hass, "turn_off")

    def test_off_timer_turns_off_after_hold_released(self, make_switch, fake_hass):
        """Releasing the hold lets the off timer reach the lights again."""
        switch, *_ = make_switch({}, day_mode=False)
        switch._state_ctrl.mark_controlled(["light.a", "light.b"])
        switch._state_ctrl.set_hold(["light.a", "light.b"], reason="service")
        fake_hass.states.set("binary_sensor.motion", FakeState(state="off"))

        switch._state_ctrl.clear_holds()

        result, _ = switch._get_mode_handler(MODE_NIGHT)._off_timer_result()

        assert result == ["light.a", "light.b"]


class TestHoldClearsOnTransition:
    """A service hold lives within one phase; a detected hold survives it."""

    def test_mode_transition_clears_service_holds(self, make_switch, fake_hass):
        switch, *_ = make_switch()
        switch._state_ctrl.set_hold(["light.a"], reason="service")

        switch._handle_mode_transition(MODE_DAY, MODE_NIGHT)

        assert switch._state_ctrl.get_held_lights() == set()

    def test_mode_transition_keeps_detected_holds(self, make_switch, fake_hass):
        """A detected hold (a scene) survives the phase change."""
        switch, *_ = make_switch()
        switch._state_ctrl.set_hold(["light.a"], reason="detected")

        switch._handle_mode_transition(MODE_DAY, MODE_NIGHT)

        assert switch._state_ctrl.get_held_lights() == {"light.a"}
        assert switch._state_ctrl.get_hold_reason("light.a") == "detected"

    def test_mode_transition_keeps_detected_and_clears_service(
        self, make_switch, fake_hass
    ):
        switch, *_ = make_switch()
        switch._state_ctrl.set_hold(["light.a"], reason="detected")
        switch._state_ctrl.set_hold(["light.b"], reason="service")

        switch._handle_mode_transition(MODE_DAY, MODE_NIGHT)

        assert switch._state_ctrl.get_held_lights() == {"light.a"}

    def test_release_hold_clears_and_reapplies(self, make_switch, fake_hass):
        switch, *_ = make_switch({}, day_mode=True)
        switch._state_ctrl.set_hold(["light.a"])
        fake_hass.states.set("sensor.lux", FakeState(state="55"))
        fake_hass.states.set("light.a", FakeState(state="off"))
        fake_hass.states.set("light.b", FakeState(state="off"))

        switch.release_hold()

        assert switch._state_ctrl.get_held_lights() == set()
        assert "light.a" in _light_entities(fake_hass)


class TestDimReleasesHold:
    """A dim press is a visitor action too, so it supersedes an on/off hold.

    Turning the lights off holds them off; the next dim press must still
    reach them instead of being swallowed by the hold.
    """

    @staticmethod
    def _force_mode(switch, mode: str):
        """Force the running mode, so the sun state cannot skew the test."""

        class _Provider:
            def get_current_mode(self) -> str:
                return mode

        switch._schedule_override = _Provider()

    @staticmethod
    def _night_dial(switch, fake_hass):
        dial = DayNightNightBrightnessNumber(switch._config_entry, "Test")
        dial.hass = fake_hass
        dial.async_write_ha_state = lambda: None
        fake_hass.data[DOMAIN][switch._config_entry.entry_id][
            KEY_NIGHT_BRIGHTNESS
        ] = dial
        return dial

    def test_dim_after_turn_off_clears_the_hold_at_night(
        self, make_switch, fake_hass
    ):
        switch, *_ = make_switch({}, day_mode=False)
        self._force_mode(switch, MODE_NIGHT)
        switch._state_ctrl.set_hold(["light.a"])
        dial = self._night_dial(switch, fake_hass)

        switch.adjust_brightness(-10)

        assert switch._state_ctrl.get_held_lights() == set()
        assert dial.dialled_in_value == 70  # configured 80, dimmed by 10

    def test_dim_after_turn_on_releases_hold(self, make_switch, fake_hass):
        """Dimming supersedes a turn_on hold."""
        switch, *_ = make_switch({}, day_mode=False)
        self._force_mode(switch, MODE_NIGHT)
        switch.record_lights_turned_on_by_service(["light.a", "light.b"])
        assert switch._state_ctrl.get_held_lights() == {"light.a", "light.b"}
        dial = self._night_dial(switch, fake_hass)

        switch.adjust_brightness(-10)

        assert switch._state_ctrl.get_held_lights() == set()
        assert dial.dialled_in_value == 70  # configured 80, dimmed by 10

    def test_release_hold_resets_dial_to_configured(
        self, make_switch, fake_hass
    ):
        """Releasing the hold restores the configured state, dial included."""
        switch, *_ = make_switch({}, day_mode=False)
        self._force_mode(switch, MODE_NIGHT)
        dial = self._night_dial(switch, fake_hass)
        dial.set_dialled_in(40)
        switch._state_ctrl.set_hold(["light.a"])

        switch.release_hold()

        assert switch._state_ctrl.get_held_lights() == set()
        assert dial.dialled_in_value is None
        assert dial.native_value == 80  # configured default


class TestReleaseHoldReturnsToNightOff:
    """Releasing a hold in a motion-lit night turns a held-on light off."""

    @staticmethod
    def _force_night(switch):
        switch._last_mode = MODE_NIGHT

        class _Provider:
            def get_current_mode(self) -> str:
                return MODE_NIGHT

        switch._schedule_override = _Provider()

    @staticmethod
    def _fire_off_timer(switch):
        if switch._action_scheduler._entries:
            switch._action_scheduler._entries[0]["run_at"] = datetime(
                2020, 1, 1, tzinfo=timezone.utc
            )
            switch._action_scheduler._run_due()

    @staticmethod
    def _turned_off(fake_hass, entity_id):
        for call in fake_hass.services.async_call.call_args_list:
            if call[0][1] != "turn_off":
                continue
            entity = call[0][2].get("entity_id")
            ids = entity if isinstance(entity, list) else [entity]
            if entity_id in ids:
                return True
        return False

    def test_release_hold_after_off_timer_skipped(self, make_switch, fake_hass):
        """The off timer fires while held and is gone; release must still off.

        Regression: releasing a hold in a motion-lit night with no motion did
        nothing (no pending off timer), so a visitor's held-on light stayed on
        forever even though the configured state with nobody present is "off".
        """
        switch, *_ = make_switch(day_mode=False)
        self._force_night(switch)

        fake_hass.states.set("binary_sensor.motion", FakeState(state="on"))
        switch._handle_motion_on()
        fake_hass.states.set(
            "light.a", FakeState(state="on", attributes={"brightness": 204})
        )
        fake_hass.states.set(
            "light.b", FakeState(state="on", attributes={"brightness": 204})
        )

        switch.record_lights_turned_on_by_service(["light.a", "light.b"])
        assert switch._state_ctrl.get_held_lights() == {"light.a", "light.b"}

        # Motion clears → off timer fires → both skipped while held.
        fake_hass.states.set("binary_sensor.motion", FakeState(state="off"))
        switch._handle_motion_off()
        self._fire_off_timer(switch)
        assert self._turned_off(fake_hass, "light.a") is False
        assert self._turned_off(fake_hass, "light.b") is False

        # Releasing the hold with nobody present must switch them off.
        switch.release_hold()

        assert switch._state_ctrl.get_held_lights() == set()
        assert self._turned_off(fake_hass, "light.a") is True
        assert self._turned_off(fake_hass, "light.b") is True

    def test_release_hold_forces_scene_light_back_to_night(
        self, make_switch, fake_hass
    ):
        """Releasing a detected hold forces the scene light back to night.

        Regression: release_hold re-applied the mode, but the motion handler
        saw the still-scene-lit light diverged and re-held it on the spot, so
        the press appeared to do nothing. The force path must command the
        light back instead of re-holding it.
        """
        switch, *_ = make_switch(day_mode=False)
        self._force_night(switch)

        # Motion active, so the room is lit at night; the light was taken
        # over by a scene (36% instead of 80%) and is held "detected".
        fake_hass.states.set("binary_sensor.motion", FakeState(state="on"))
        switch._state_ctrl.mark_controlled(["light.a"])
        switch._state_ctrl.set_hold(["light.a"], reason="detected")
        fake_hass.states.set(
            "light.a",
            FakeState(state="on", attributes={"brightness": 92, "color_temp": 225}),
        )
        fake_hass.states.set("light.b", FakeState(state="off"))

        fake_hass.services.async_call.reset_mock()
        switch.release_hold()

        # Hold cleared, and the scene light was commanded back on (night
        # target), not re-held.
        assert switch._state_ctrl.get_held_lights() == set()
        assert not switch._state_ctrl.is_held("light.a")
        assert "light.a" in _light_entities(fake_hass, "turn_on")


class TestHoldSkipsRamps:
    """Sleep and wake-up also leave held lights alone in their ramps."""

    def test_sleep_ramp_skips_held_light(self, fake_hass):
        shared, mocks = _handler_shared(fake_hass, held={"light.a"})
        illuminance = MagicMock()
        illuminance.get_lux.return_value = None
        handler = SleepModeHandler(
            shared=shared,
            config=SimpleNamespace(
                duration_min=30,
                target_brightness=10,
                target_kelvin=2200,
                use_auto_values=False,
            ),
            illuminance=illuminance,
            day_mode_config=SimpleNamespace(max_brightness=100),
            night_mode_config=SimpleNamespace(brightness=80),
            schedule=MagicMock(),
            circadian=mocks["circadian"],
        )
        handler._sleep_active = True
        handler._sleep_start_time = None  # progress 0 → dimming phase

        handler._apply_sleep_mode()

        mocks["state_ctrl"].mark_controlled.assert_called_with(["light.b"])

    def test_wakeup_ramp_skips_held_light(self, fake_hass):
        shared, mocks = _handler_shared(fake_hass, held={"light.a"})
        handler = WakeUpModeHandler(
            shared=shared,
            config=SimpleNamespace(
                start_brightness=1,
                end_brightness=100,
                end_kelvin=5500,
                use_auto_values=False,
                duration_min=30,
            ),
            illuminance=MagicMock(),
            schedule=MagicMock(),
            circadian=mocks["circadian"],
            day_mode_config=SimpleNamespace(max_brightness=100),
            night_mode_config=SimpleNamespace(brightness=80),
        )
        handler._wakeup_active = True
        handler._wakeup_start_time = dt_util.now()
        handler._wakeup_service_duration_min = 30

        handler._apply_wakeup_mode()

        mocks["state_ctrl"].mark_controlled.assert_called_with(["light.b"])
