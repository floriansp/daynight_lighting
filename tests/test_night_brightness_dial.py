"""Tests for the night brightness dial.

The dial exists so that a wall button can dim a room at night without the
integration treating it as an external override. These tests cover the value
itself, the places in night mode that have to honour it, and the reset when a
new night starts.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from custom_components.daynight_lighting.const import (
    DOMAIN,
    MIN_DIAL_BRIGHTNESS_PCT,
    MIN_NIGHT_SENSOR_BRIGHTNESS_PCT,
    MODE_DAY,
    MODE_NIGHT,
)
from custom_components.daynight_lighting.context import SharedHandlerDeps
from custom_components.daynight_lighting.handlers import NightModeHandler
from custom_components.daynight_lighting.number import (
    MAX_NIGHT_BRIGHTNESS,
    MIN_NIGHT_BRIGHTNESS,
    DayNightNightBrightnessNumber,
    async_setup_entry,
)

from tests.conftest import FakeState
from tests.test_event_driven_detection import _make_switch_with_mocks

CONFIGURED = 40


def _make_entry(night_brightness: int = CONFIGURED) -> SimpleNamespace:
    return SimpleNamespace(
        entry_id="test_entry",
        data={"instance_name": "Test"},
        options={"instance_name": "Test", "night_brightness": night_brightness},
    )


def _make_dial(fake_hass, night_brightness: int = CONFIGURED):
    entry = _make_entry(night_brightness)
    dial = DayNightNightBrightnessNumber(entry, "Test")
    dial.hass = fake_hass
    dial.async_write_ha_state = lambda: None
    return dial


def _make_night_handler(fake_hass, get_night_brightness, get_held_lights=None):
    """Night handler wired to a dial value, with everything else mocked."""
    mocks = {
        "state_ctrl": MagicMock(),
        "circadian": MagicMock(),
        "lights": MagicMock(),
    }
    mocks["circadian"].is_enabled.return_value = True
    mocks["circadian"].get_expected_night_kelvin.return_value = 2200
    mocks["lights"].get_lights_list.return_value = ["light.a"]

    motion = MagicMock()
    motion.get_motion_sensor_entity.return_value = "binary_sensor.motion"
    motion.has_motion_now.return_value = True

    shared = SharedHandlerDeps(
        hass=fake_hass,
        instance_name="Test",
        lights=mocks["lights"],
        state_ctrl=mocks["state_ctrl"],
        is_control_brightness_on=lambda: True,
        is_control_color_on=lambda: True,
        get_transition=lambda ctx: 0,
        get_night_brightness=get_night_brightness,
        get_held_lights=get_held_lights or (lambda: set()),
    )
    handler = NightModeHandler(
        shared=shared,
        config=SimpleNamespace(
            brightness=CONFIGURED,
            fallback="on",
            motion_off_delay_min=5,
            on_enter_night="leave",
        ),
        motion=motion,
        action_scheduler=MagicMock(),
        circadian=mocks["circadian"],
    )
    return handler, mocks


class TestDialValue:
    """The dial holds the value; the configuration is its starting point."""

    def test_starts_at_the_configured_value(self, fake_hass):
        dial = _make_dial(fake_hass)
        assert dial.native_value == CONFIGURED
        assert dial.dialled_in_value is None

    def test_dialling_in_sets_the_value(self, fake_hass):
        dial = _make_dial(fake_hass)
        dial.set_dialled_in(15)
        assert dial.native_value == 15
        assert dial.dialled_in_value == 15

    def test_never_reaches_off(self, fake_hass):
        """Dimming must not become an off switch."""
        dial = _make_dial(fake_hass)
        dial.set_dialled_in(-30)
        assert dial.native_value == MIN_NIGHT_BRIGHTNESS
        assert dial.native_value > 0

    def test_stops_at_the_floor_not_at_one_percent(self, fake_hass):
        """A stairwell dialled down to 1% would be as dark as switched off."""
        dial = _make_dial(fake_hass)
        dial.set_dialled_in(3)
        assert dial.native_value == MIN_DIAL_BRIGHTNESS_PCT

    def test_a_configuration_below_the_floor_wins(self, fake_hass):
        """The floor guards the button, not a deliberate configuration."""
        dial = _make_dial(fake_hass, night_brightness=2)
        assert dial.native_min_value == 2
        assert dial.native_value == 2

    def test_the_floor_applies_above_a_low_configuration(self, fake_hass):
        dial = _make_dial(fake_hass, night_brightness=2)
        dial.set_dialled_in(1)
        assert dial.native_value == 2

    def test_clamps_at_the_top(self, fake_hass):
        dial = _make_dial(fake_hass)
        dial.set_dialled_in(180)
        assert dial.native_value == MAX_NIGHT_BRIGHTNESS

    def test_reset_returns_to_the_configuration(self, fake_hass):
        dial = _make_dial(fake_hass)
        dial.set_dialled_in(15)
        dial.reset()
        assert dial.native_value == CONFIGURED
        assert dial.dialled_in_value is None

    @pytest.mark.asyncio
    async def test_set_native_value_rounds(self, fake_hass):
        dial = _make_dial(fake_hass)
        await dial.async_set_native_value(17.6)
        assert dial.native_value == 18

    @pytest.mark.asyncio
    async def test_setup_registers_the_dial_for_the_handlers(self, fake_hass):
        entry = _make_entry()
        added = []

        await async_setup_entry(fake_hass, entry, lambda e: added.extend(e))

        registered = fake_hass.data[DOMAIN][entry.entry_id]["night_brightness_number"]
        assert registered in added
        assert isinstance(registered, DayNightNightBrightnessNumber)


class TestNightModeHonoursTheDial:
    """Every night-mode path has to use the dialled-in value."""

    def test_motion_turn_on_uses_the_dial(self, fake_hass):
        handler, mocks = _make_night_handler(fake_hass, lambda: 15)
        fake_hass.states.set("light.a", FakeState(state="off", attributes={}))

        handler.handle_motion_on()

        mocks["state_ctrl"].set_expected_state.assert_called_once()
        assert mocks["state_ctrl"].set_expected_state.call_args.kwargs[
            "brightness_pct"
        ] == 15

    def test_expected_state_uses_the_dial(self, fake_hass):
        handler, _ = _make_night_handler(fake_hass, lambda: 15)
        assert handler.calculate_expected_state().brightness_pct == 15

    def test_falls_back_to_the_configuration(self, fake_hass):
        handler, _ = _make_night_handler(fake_hass, lambda: None)
        assert handler.calculate_expected_state().brightness_pct == CONFIGURED

    def test_dimmed_light_still_counts_as_matching(self, fake_hass):
        """The guard that aborts motion turn-on must compare against the dial.

        Without this, a dimmed light looks like a foreign value and
        handle_motion_on() bails out for the whole room.
        """
        handler, _ = _make_night_handler(fake_hass, lambda: 15)
        # 15% of 255 ≈ 38
        fake_hass.states.set(
            "light.a", FakeState(state="on", attributes={"brightness": 38})
        )

        assert handler._light_matches_night_values("light.a") is True

    def test_motion_turn_on_survives_a_dimmed_light(self, fake_hass):
        """The whole point: dimmed at night, motion still applies the dial."""
        handler, mocks = _make_night_handler(fake_hass, lambda: 15)
        mocks["state_ctrl"].is_controlled_by_us.return_value = False
        fake_hass.states.set(
            "light.a", FakeState(state="on", attributes={"brightness": 38})
        )

        handler.handle_motion_on()

        mocks["state_ctrl"].mark_controlled.assert_called_once()


class TestReapplyToOnLights:
    """Changing the dial re-dims the lights that are already on."""

    def test_on_lights_follow_the_dial(self, fake_hass):
        handler, mocks = _make_night_handler(fake_hass, lambda: 15)
        fake_hass.states.set(
            "light.a", FakeState(state="on", attributes={"brightness": 200})
        )

        handler.reapply_brightness_to_on_lights()

        mocks["state_ctrl"].mark_controlled.assert_called_once_with(["light.a"])
        mocks["state_ctrl"].set_expected_state.assert_called_once_with(
            "light.a", on=True, brightness_pct=15, kelvin=2200
        )

    def test_off_lights_are_left_alone(self, fake_hass):
        handler, mocks = _make_night_handler(fake_hass, lambda: 15)
        fake_hass.states.set("light.a", FakeState(state="off"))

        handler.reapply_brightness_to_on_lights()

        mocks["state_ctrl"].mark_controlled.assert_not_called()

    def test_held_lights_stop_the_reapply(self, fake_hass):
        handler, mocks = _make_night_handler(
            fake_hass, lambda: 15, get_held_lights=lambda: {"light.a"}
        )
        fake_hass.states.set(
            "light.a", FakeState(state="on", attributes={"brightness": 200})
        )

        handler.reapply_brightness_to_on_lights()

        mocks["state_ctrl"].mark_controlled.assert_not_called()


class TestResetOnEnteringTheNight:
    """A new night starts from the configured value."""

    def test_entering_night_resets_the_dial(self, fake_hass, fake_store):
        switch, *_ = _make_switch_with_mocks(fake_hass, fake_store)
        dial = _make_dial(fake_hass)
        fake_hass.data[DOMAIN]["test_entry"]["night_brightness_number"] = dial
        dial.set_dialled_in(15)

        switch._handle_mode_transition(MODE_DAY, MODE_NIGHT)

        assert dial.dialled_in_value is None

    def test_other_transitions_keep_the_dial(self, fake_hass, fake_store):
        switch, *_ = _make_switch_with_mocks(fake_hass, fake_store)
        dial = _make_dial(fake_hass)
        fake_hass.data[DOMAIN]["test_entry"]["night_brightness_number"] = dial
        dial.set_dialled_in(15)

        switch._handle_mode_transition(MODE_NIGHT, MODE_DAY)

        assert dial.dialled_in_value == 15

    def test_switch_reads_the_dial(self, fake_hass, fake_store):
        switch, *_ = _make_switch_with_mocks(fake_hass, fake_store)
        dial = _make_dial(fake_hass)
        fake_hass.data[DOMAIN]["test_entry"]["night_brightness_number"] = dial

        assert switch._get_night_brightness() is None
        dial.set_dialled_in(15)
        assert switch._get_night_brightness() == 15

    def test_works_without_the_dial(self, fake_hass, fake_store):
        """A removed or disabled number entity must not break anything."""
        switch, *_ = _make_switch_with_mocks(fake_hass, fake_store)
        assert switch._get_night_brightness() is None
        switch._reset_night_brightness_dial()


class TestConfigurationWins:
    """The configuration dialog is the baseline; the dial sits on top of it."""

    def test_dial_follows_a_changed_configuration(self, fake_hass):
        dial = _make_dial(fake_hass)
        dial._config_entry.options["night_brightness"] = 60

        assert dial.native_value == 60

    def test_changing_the_option_drops_the_dial(self, fake_hass, fake_store):
        """A new configured value is a deliberate baseline, so the dial goes."""
        switch, *_ = _make_switch_with_mocks(fake_hass, fake_store)
        dial = _make_dial(fake_hass)
        fake_hass.data[DOMAIN]["test_entry"]["night_brightness_number"] = dial
        dial.set_dialled_in(15)

        switch.async_options_changed()

        assert dial.dialled_in_value is None
        assert dial.native_value == CONFIGURED

    def test_reset_without_apply_still_publishes(self, fake_hass):
        """The value must reach the UI even when the caller re-applies."""
        dial = _make_dial(fake_hass)
        writes: list[int] = []
        dial.async_write_ha_state = lambda: writes.append(1)
        dial.set_dialled_in(15)
        writes.clear()

        dial.reset(apply=False)

        assert writes, "state was not published"

    def test_dial_does_not_poll(self, fake_hass):
        assert _make_dial(fake_hass).should_poll is False


class TestNightSensorFloor:
    """A motion-lit room dims to 5 % at most, never into darkness."""

    def test_floor_is_five_with_a_motion_sensor(self, make_switch, fake_hass):
        switch, *_ = make_switch({})  # motion_sensor configured by default
        dial = _make_dial(fake_hass)
        fake_hass.data[DOMAIN]["test_entry"]["night_brightness_number"] = dial
        assert dial.native_min_value == MIN_NIGHT_SENSOR_BRIGHTNESS_PCT

    def test_floor_stays_ten_without_a_motion_sensor(self, make_switch, fake_hass):
        switch, *_ = make_switch({"motion_sensor": None})
        dial = _make_dial(fake_hass)
        fake_hass.data[DOMAIN]["test_entry"]["night_brightness_number"] = dial
        assert dial.native_min_value == MIN_NIGHT_BRIGHTNESS

    def test_floor_wins_over_a_lower_configuration(self, make_switch, fake_hass):
        switch, *_ = make_switch({})
        dial = _make_dial(fake_hass, night_brightness=2)
        fake_hass.data[DOMAIN]["test_entry"]["night_brightness_number"] = dial
        # The configuration below 5 is deliberate (e.g. a bedroom), it wins.
        assert dial.native_min_value == 2
