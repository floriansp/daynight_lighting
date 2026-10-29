"""Tests for what a wall button press does, mode by mode.

One rule decides: a step is applied to the lights where nothing here
controls their brightness, it moves the target where we aim at a fixed
value, and it is ignored where neither is possible. Manual control is never
part of it — a press is our own doing, not an intervention to step aside
for. Getting that wrong is how a button either does nothing or takes the
room hostage for half an hour.
"""

from __future__ import annotations

import pytest

from custom_components.daynight_lighting.const import (
    DOMAIN,
    MIN_DIAL_BRIGHTNESS_PCT,
    MODE_DAY,
    MODE_NIGHT,
    MODE_SLEEP,
    MODE_WAKEUP,
)
from custom_components.daynight_lighting.number import (
    DayNightDayBrightnessNumber,
    DayNightNightBrightnessNumber,
)

from tests.conftest import FakeState

NO_SENSOR = {"light_sensor": None}
FIXED_AT_70 = {
    "light_sensor": None,
    "day_mode_fallback": "fixed",
    "day_fixed_brightness_pct": 70,
}


def _instance(
    make_switch,
    fake_hass,
    options: dict | None = None,
    *,
    mode: str = MODE_DAY,
    lights: dict[str, int | None] | None = None,
    dial: bool = False,
):
    """An instance in *mode*, with *lights* at the given brightness.

    Returns ``(switch, dial)``; the dial is None unless asked for, because
    the brightness dials are a separate platform. With it, the dial of
    *mode* is returned: the night dial at night, else the day one.
    """
    switch, *_ = make_switch(options or {}, day_mode=(mode == MODE_DAY))
    _set_mode(switch, mode)

    for entity_id, pct in (lights or {}).items():
        if pct is None:
            fake_hass.states.set(entity_id, FakeState(state="off"))
        else:
            fake_hass.states.set(
                entity_id,
                FakeState(
                    state="on", attributes={"brightness": round(pct / 100 * 255)}
                ),
            )

    dial_entity = _add_dial(switch, fake_hass, mode) if dial else None

    return switch, dial_entity


def _set_mode(switch, mode: str):
    """Force the running mode, so the schedule cannot skew these tests."""

    class _Provider:
        def get_current_mode(self) -> str:
            return mode

        def is_day_mode(self) -> bool:
            return mode == MODE_DAY

        def get_mode_and_time_for_log(self):
            return (mode, "")

    switch._schedule_override = _Provider()


def _add_dial(switch, fake_hass, mode: str = MODE_NIGHT):
    """Give the instance both brightness dials, as setup would.

    Returns the dial the given *mode* reads.
    """
    instance = fake_hass.data[DOMAIN][switch._config_entry.entry_id]
    dials = {}
    for key, cls, dial_mode in (
        ("night_brightness_number", DayNightNightBrightnessNumber, MODE_NIGHT),
        ("day_brightness_number", DayNightDayBrightnessNumber, MODE_DAY),
    ):
        dial = cls(switch._config_entry, "Test")
        dial.hass = fake_hass
        dial.async_write_ha_state = lambda: None
        instance[key] = dial
        dials[dial_mode] = dial
    return dials[MODE_NIGHT] if mode == MODE_NIGHT else dials[MODE_DAY]


def _light_calls(fake_hass) -> list[dict]:
    """Payloads of the light.turn_on calls, in order."""
    return [
        call[0][2]
        for call in fake_hass.services.async_call.call_args_list
        if call[0][0] == "light" and call[0][1] == "turn_on"
    ]


def _targets(fake_hass) -> dict[str, int]:
    """Brightness each light was commanded to."""
    result = {}
    for payload in _light_calls(fake_hass):
        entity = payload["entity_id"]
        if isinstance(entity, list):
            entity = entity[0]
        if "brightness_pct" in payload:
            result[entity] = payload["brightness_pct"]
    return result


class TestNight:
    """Night runs open loop on a value, so the step moves that value."""

    def test_the_step_moves_the_dial(self, make_switch, fake_hass):
        switch, dial = _instance(
            make_switch, fake_hass, mode=MODE_NIGHT, dial=True
        )

        switch.adjust_brightness(-15)

        assert dial.dialled_in_value == 65  # configured 80

    def test_without_a_dial_the_press_is_ignored(self, make_switch, fake_hass):
        """A disabled number entity must not send the lights somewhere else."""
        switch, *_ = _instance(
            make_switch,
            fake_hass,
            mode=MODE_NIGHT,
            lights={"light.a": 50, "light.b": 50},
        )

        switch.adjust_brightness(10)

        assert _light_calls(fake_hass) == []

    def test_the_step_reaches_an_on_light_when_motion_is_absent(
        self, make_switch, fake_hass
    ):
        """A held-on light dims at once, without a fresh motion event."""
        switch, dial = _instance(
            make_switch,
            fake_hass,
            mode=MODE_NIGHT,
            lights={"light.a": 80, "light.b": 80},
            dial=True,
        )
        switch._last_mode = MODE_NIGHT
        fake_hass.states.set("binary_sensor.motion", FakeState(state="off"))

        switch.adjust_brightness(-20)

        assert dial.dialled_in_value == 60
        calls = _light_calls(fake_hass)
        assert len(calls) == 1
        assert calls[0]["entity_id"] == ["light.a", "light.b"]
        assert calls[0]["brightness_pct"] == 60

    def test_the_step_reaches_an_on_light_without_a_motion_sensor(
        self, make_switch, fake_hass
    ):
        """Open-loop night dims the on lights even with no motion sensor."""
        switch, dial = _instance(
            make_switch,
            fake_hass,
            {"motion_sensor": None},
            mode=MODE_NIGHT,
            lights={"light.a": 80, "light.b": 80},
            dial=True,
        )
        switch._last_mode = MODE_NIGHT

        switch.adjust_brightness(-20)

        assert dial.dialled_in_value == 60
        calls = _light_calls(fake_hass)
        assert len(calls) == 1
        assert calls[0]["brightness_pct"] == 60

    def test_an_off_light_stays_off_when_dimmed(self, make_switch, fake_hass):
        """A dial is not an on switch: dimming leaves an off light off."""
        switch, dial = _instance(
            make_switch,
            fake_hass,
            mode=MODE_NIGHT,
            lights={"light.a": None},
            dial=True,
        )
        switch._last_mode = MODE_NIGHT

        switch.adjust_brightness(-20)

        assert dial.dialled_in_value == 60
        assert _light_calls(fake_hass) == []


class TestDayWithLuxSensor:
    """With a LUX sensor the curve keeps regulating, so a step cannot be held."""

    def _day(self, make_switch, fake_hass, lux: float, **kwargs):
        switch, dial = _instance(
            make_switch, fake_hass, dial=True, **kwargs
        )
        fake_hass.states.set("sensor.lux", FakeState(state=str(lux)))
        return switch, dial

    def test_the_press_is_ignored(self, make_switch, fake_hass):
        switch, _ = self._day(make_switch, fake_hass, 55)

        reason = switch.adjust_brightness(-20)

        assert "LUX-regulated" in reason
        assert _light_calls(fake_hass) == []

    def test_without_the_dial_the_press_is_ignored(self, make_switch, fake_hass):
        """A disabled number entity must not send the lights somewhere else."""
        switch, *_ = _instance(make_switch, fake_hass)
        fake_hass.states.set("sensor.lux", FakeState(state="55"))

        switch.adjust_brightness(-20)

        assert _light_calls(fake_hass) == []


class TestDayWithoutLuxSensor:
    """What the day mode does with the brightness decides the answer."""

    def test_skip_fallback_lets_the_step_stand(self, make_switch, fake_hass):
        """Skip sets no brightness, so the step stands on the lights."""
        switch, *_ = _instance(
            make_switch,
            fake_hass,
            {**NO_SENSOR, "day_mode_fallback": "skip"},
            lights={"light.a": 40, "light.b": 70},
        )

        switch.adjust_brightness(10)

        assert _targets(fake_hass) == {"light.a": 50, "light.b": 80}

    def test_circadian_only_ignores_the_press(self, make_switch, fake_hass):
        """Circadian only controls colour, there is no brightness to dim."""
        switch, *_ = _instance(
            make_switch,
            fake_hass,
            {**NO_SENSOR, "day_mode_fallback": "circadian_only"},
            lights={"light.a": 40, "light.b": 70},
        )

        switch.adjust_brightness(10)

        assert _light_calls(fake_hass) == []

    def test_the_fixed_fallback_moves_its_target(self, make_switch, fake_hass):
        """Stepping the lights would be overwritten by the next tick."""
        switch, dial = _instance(
            make_switch, fake_hass, FIXED_AT_70, lights={"light.a": 70}, dial=True
        )

        switch.adjust_brightness(-20)

        assert switch._get_mode_handler(MODE_DAY).target_fixed_brightness() == 50
        assert dial.dialled_in_value == 50

    def test_the_moved_target_survives_the_next_tick(
        self, make_switch, fake_hass
    ):
        switch, *_ = _instance(make_switch, fake_hass, FIXED_AT_70, dial=True)
        switch.adjust_brightness(-20)
        fake_hass.services.async_call.reset_mock()

        switch._get_mode_handler(MODE_DAY).tick()

        assert _light_calls(fake_hass)[0]["brightness_pct"] == 50

    def test_the_check_agrees_with_what_was_applied(
        self, make_switch, fake_hass
    ):
        """A mismatch here reports our own dimming as external control."""
        switch, *_ = _instance(make_switch, fake_hass, FIXED_AT_70, dial=True)

        switch.adjust_brightness(-20)

        expected = switch._get_mode_handler(MODE_DAY).calculate_expected_state()
        assert expected.brightness_pct == 50

    def test_a_new_day_starts_from_the_configured_value(
        self, make_switch, fake_hass
    ):
        switch, dial = _instance(make_switch, fake_hass, FIXED_AT_70, dial=True)
        switch.adjust_brightness(-20)

        switch._handle_mode_transition(MODE_NIGHT, MODE_DAY)

        assert dial.dialled_in_value is None
        assert switch._get_mode_handler(MODE_DAY).target_fixed_brightness() == 70

    def test_a_fallback_that_wants_darkness_ignores_the_press(
        self, make_switch, fake_hass
    ):
        switch, *_ = _instance(
            make_switch,
            fake_hass,
            {**NO_SENSOR, "day_mode_fallback": "off"},
            lights={"light.a": 40, "light.b": 40},
        )

        switch.adjust_brightness(10)

        assert _light_calls(fake_hass) == []


class TestRamps:
    """Sleep and wake-up recompute from the clock on every tick."""

    @pytest.mark.parametrize("mode", [MODE_SLEEP, MODE_WAKEUP])
    def test_the_press_is_ignored(self, make_switch, fake_hass, mode):
        switch, *_ = _instance(
            make_switch,
            fake_hass,
            NO_SENSOR,
            mode=mode,
            lights={"light.a": 40, "light.b": 40},
        )

        switch.adjust_brightness(-10)

        assert _light_calls(fake_hass) == []


class TestFloor:
    """A wall button must never be able to switch a light off."""

    def test_dimming_stops_above_darkness(self, make_switch, fake_hass):
        switch, *_ = _instance(
            make_switch,
            fake_hass,
            NO_SENSOR,
            lights={"light.a": 15, "light.b": 15},
        )

        switch.adjust_brightness(-50)

        assert _targets(fake_hass) == {
            "light.a": MIN_DIAL_BRIGHTNESS_PCT,
            "light.b": MIN_DIAL_BRIGHTNESS_PCT,
        }

    def test_brightening_stops_at_full(self, make_switch, fake_hass):
        switch, *_ = _instance(
            make_switch,
            fake_hass,
            NO_SENSOR,
            lights={"light.a": 95, "light.b": 95},
        )

        switch.adjust_brightness(20)

        assert _targets(fake_hass) == {"light.a": 100, "light.b": 100}

    def test_dimming_leaves_an_off_light_off(self, make_switch, fake_hass):
        switch, *_ = _instance(
            make_switch,
            fake_hass,
            NO_SENSOR,
            lights={"light.a": None, "light.b": 60},
        )

        switch.adjust_brightness(-10)

        assert _targets(fake_hass) == {"light.b": 50}

    def test_brightening_wakes_an_off_light_at_the_floor(
        self, make_switch, fake_hass
    ):
        switch, *_ = _instance(
            make_switch,
            fake_hass,
            NO_SENSOR,
            lights={"light.a": None, "light.b": None},
        )

        switch.adjust_brightness(5)

        assert _targets(fake_hass) == {
            "light.a": MIN_DIAL_BRIGHTNESS_PCT,
            "light.b": MIN_DIAL_BRIGHTNESS_PCT,
        }


class TestResetBrightness:
    """A dim without a hold is undone by reset_brightness."""

    def test_night_dim_then_reset(self, make_switch, fake_hass):
        switch, dial = _instance(
            make_switch, fake_hass, mode=MODE_NIGHT, dial=True
        )

        switch.adjust_brightness(-15)
        assert switch.has_dialled_brightness() is True
        assert dial.dialled_in_value == 65  # configured 80

        switch.reset_brightness()

        assert dial.dialled_in_value is None
        assert switch.has_dialled_brightness() is False

    def test_day_fixed_dim_then_reset(self, make_switch, fake_hass):
        switch, dial = _instance(
            make_switch, fake_hass, FIXED_AT_70, dial=True
        )

        switch.adjust_brightness(-20)
        assert switch.has_dialled_brightness() is True
        assert dial.dialled_in_value == 50

        switch.reset_brightness()

        assert dial.dialled_in_value is None
        assert switch._get_mode_handler(MODE_DAY).target_fixed_brightness() == 70

    def test_lux_day_has_nothing_to_reset(self, make_switch, fake_hass):
        switch, *_ = _instance(make_switch, fake_hass)
        fake_hass.states.set("sensor.lux", FakeState(state="55"))

        assert switch.has_dialled_brightness() is False

    def test_the_other_phases_dial_is_left_alone(self, make_switch, fake_hass):
        """Resetting at night must not touch the stale day dial, and vice versa."""
        switch, dial = _instance(
            make_switch, fake_hass, mode=MODE_NIGHT, dial=True
        )
        # A stale day dial from earlier in the day is not ours to reset at night.
        day_dial = fake_hass.data[DOMAIN][switch._config_entry.entry_id][
            "day_brightness_number"
        ]
        day_dial.set_dialled_in(40)

        switch.reset_brightness()

        assert day_dial.dialled_in_value == 40
        assert dial.dialled_in_value is None

    def test_motion_night_reset_reapplies_not_holds(self, make_switch, fake_hass):
        """Resetting a dim in a motion-lit night returns the light, no hold.

        Regression: reset_brightness re-applied the mode through the motion
        handler, which saw the still-dimmed light as a divergence and held it
        "detected" on the spot. The press must re-dim the light back to the
        configured brightness instead.
        """
        switch, dial = _instance(
            make_switch,
            fake_hass,
            mode=MODE_NIGHT,
            lights={"light.a": 80, "light.b": None},
            dial=True,
        )
        switch._last_mode = MODE_NIGHT
        fake_hass.states.set("binary_sensor.motion", FakeState(state="on"))
        switch._state_ctrl.mark_controlled(["light.a"])

        # The wall button dims the light to 60%; the bulb reports that value
        # (with a real colour temperature, as an XY/white bulb would).
        switch.adjust_brightness(-20)
        assert dial.dialled_in_value == 60
        assert switch.has_dialled_brightness() is True
        fake_hass.states.set(
            "light.a",
            FakeState(
                state="on", attributes={"brightness": 153, "color_temp": 225}
            ),
        )

        # The dim's grace period has long expired by the time the user reaches
        # for the reset button, so the motion handler can no longer mistake it
        # for our own in-flight command.
        switch._manual_control_detector._last_applied_time = {}

        fake_hass.services.async_call.reset_mock()
        switch.reset_brightness()

        assert dial.dialled_in_value is None
        assert switch.has_dialled_brightness() is False
        assert switch._state_ctrl.get_held_lights() == set()
        # The dimmed light returns to the configured 80%; the off light stays
        # off — resetting a dim is not an on switch.
        assert _targets(fake_hass) == {"light.a": 80}
