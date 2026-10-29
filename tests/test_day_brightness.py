"""Tests for the day brightness dial.

Day mode only has a single target when it runs without a LUX sensor on the
*fixed* fallback; there the dial holds an absolute brightness, like the night
dial. With a LUX sensor there is no single value to show, so the dial does not
apply. These tests cover the value, the places day mode has to honour it, and
the reset when a new day starts.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from custom_components.daynight_lighting.const import DOMAIN, MODE_DAY, MODE_NIGHT
from custom_components.daynight_lighting.number import (
    DayNightDayBrightnessNumber,
    DayNightNightBrightnessNumber,
    async_setup_entry,
)

from tests.conftest import FakeState

CONFIGURED = 70


def _make_entry(day_fixed: int = CONFIGURED) -> SimpleNamespace:
    return SimpleNamespace(
        entry_id="test_entry",
        data={"instance_name": "Test"},
        options={"instance_name": "Test", "day_fixed_brightness_pct": day_fixed},
    )


def _make_dial(fake_hass, day_fixed: int = CONFIGURED):
    entry = _make_entry(day_fixed)
    dial = DayNightDayBrightnessNumber(entry, "Test")
    dial.hass = fake_hass
    dial.async_write_ha_state = lambda: None
    return dial


def _day_instance(make_switch, fake_hass, options=None):
    """A day instance on the fixed fallback, its day dial registered."""
    switch, *_ = make_switch(
        {
            "light_sensor": None,
            "day_mode_fallback": "fixed",
            "day_fixed_brightness_pct": CONFIGURED,
            **(options or {}),
        },
        day_mode=True,
    )
    dial = DayNightDayBrightnessNumber(switch._config_entry, "Test")
    dial.hass = fake_hass
    dial.async_write_ha_state = lambda: None
    fake_hass.data[DOMAIN][switch._config_entry.entry_id]["day_brightness_number"] = dial
    for eid in ("light.a", "light.b"):
        fake_hass.states.set(
            eid,
            FakeState(state="on", attributes={"brightness": round(CONFIGURED / 100 * 255)}),
        )
    return switch, dial


class TestDialValue:
    """The dial holds the value; the configuration is its starting point."""

    def test_starts_at_the_configured_value(self, fake_hass):
        dial = _make_dial(fake_hass)
        assert dial.native_value == CONFIGURED
        assert dial.dialled_in_value is None

    def test_dialling_in_sets_the_value(self, fake_hass):
        dial = _make_dial(fake_hass)
        dial.set_dialled_in(40)
        assert dial.native_value == 40
        assert dial.dialled_in_value == 40

    def test_clamps_to_the_percent_range(self, fake_hass):
        dial = _make_dial(fake_hass)
        dial.set_dialled_in(180)
        assert dial.native_value == 100
        dial.set_dialled_in(-30)
        assert dial.native_value == 0

    def test_reset_returns_to_the_configuration(self, fake_hass):
        dial = _make_dial(fake_hass)
        dial.set_dialled_in(40)
        dial.reset(apply=False)
        assert dial.native_value == CONFIGURED
        assert dial.dialled_in_value is None

    @pytest.mark.asyncio
    async def test_set_native_value_rounds(self, fake_hass):
        dial = _make_dial(fake_hass)
        await dial.async_set_native_value(41.6)
        assert dial.native_value == 42

    @pytest.mark.asyncio
    async def test_restored_after_a_restart(self, fake_hass):
        dial = _make_dial(fake_hass)
        dial.async_get_last_state = AsyncMock(return_value=FakeState(state="45"))
        await dial.async_added_to_hass()
        assert dial.dialled_in_value == 45

    @pytest.mark.asyncio
    async def test_a_restored_configured_value_is_not_dialled(self, fake_hass):
        """Equal to the configuration carries no information."""
        dial = _make_dial(fake_hass)
        dial.async_get_last_state = AsyncMock(return_value=FakeState(state=str(CONFIGURED)))
        await dial.async_added_to_hass()
        assert dial.dialled_in_value is None

    @pytest.mark.asyncio
    async def test_setup_registers_both_dials(self, fake_hass):
        entry = _make_entry()
        added = []

        await async_setup_entry(fake_hass, entry, lambda e: added.extend(e))

        instance = fake_hass.data[DOMAIN][entry.entry_id]
        assert isinstance(instance["night_brightness_number"], DayNightNightBrightnessNumber)
        assert isinstance(instance["day_brightness_number"], DayNightDayBrightnessNumber)
        assert len(added) == 2


class TestDayModeHonoursTheDial:
    """The fixed-fallback day mode has to use the dialled-in value."""

    def test_target_fixed_brightness_falls_back_to_configuration(
        self, make_switch, fake_hass
    ):
        switch, _ = _day_instance(make_switch, fake_hass)
        handler = switch._get_mode_handler(MODE_DAY)
        assert handler.target_fixed_brightness() == CONFIGURED

    def test_target_fixed_brightness_uses_the_dial(self, make_switch, fake_hass):
        switch, dial = _day_instance(make_switch, fake_hass)
        dial.set_dialled_in(40)
        handler = switch._get_mode_handler(MODE_DAY)
        assert handler.target_fixed_brightness() == 40

    def test_adjust_brightness_moves_the_dial(self, make_switch, fake_hass):
        switch, dial = _day_instance(make_switch, fake_hass)

        reason = switch.adjust_brightness(-20)

        assert dial.dialled_in_value == CONFIGURED - 20
        assert "50%" in reason

    def test_adjust_brightness_is_ignored_without_a_dial(
        self, make_switch, fake_hass
    ):
        switch, _ = _day_instance(make_switch, fake_hass)
        # Remove the dial: the button must not send the lights somewhere else.
        del fake_hass.data[DOMAIN][switch._config_entry.entry_id]["day_brightness_number"]

        reason = switch.adjust_brightness(-20)

        assert "no day brightness dial" in reason


class TestAvailability:
    """The dial is hidden while a LUX sensor drives the brightness instead."""

    def test_available_without_a_lux_sensor(self, make_switch, fake_hass):
        """No LUX sensor → the fixed-fallback dial is the real control."""
        switch, dial = _day_instance(make_switch, fake_hass)

        assert switch.has_lux_sensor() is False
        assert dial.available is True

    def test_unavailable_with_a_lux_sensor(self, make_switch, fake_hass):
        """A LUX sensor regulates the brightness, so the dial is meaningless."""
        switch, *_ = make_switch(
            {"light_sensor": "sensor.lux", "day_mode_fallback": "fixed"},
            day_mode=True,
        )
        dial = DayNightDayBrightnessNumber(switch._config_entry, "Test")
        dial.hass = fake_hass

        assert switch.has_lux_sensor() is True
        assert dial.available is False


class TestResetOnEnteringTheDay:
    """A new day starts from the configured value."""

    def test_entering_day_resets_the_dial(self, make_switch, fake_hass):
        switch, dial = _day_instance(make_switch, fake_hass)
        dial.set_dialled_in(40)

        switch._handle_mode_transition(MODE_NIGHT, MODE_DAY)

        assert dial.dialled_in_value is None

    def test_entering_night_keeps_it(self, make_switch, fake_hass):
        """Irrelevant at night, and the next day resets it anyway."""
        switch, dial = _day_instance(make_switch, fake_hass)
        dial.set_dialled_in(40)

        switch._handle_mode_transition(MODE_DAY, MODE_NIGHT)

        assert dial.dialled_in_value == 40

    def test_an_options_change_resets(self, make_switch, fake_hass):
        """A new configuration is a deliberate baseline, the dialog wins."""
        switch, dial = _day_instance(make_switch, fake_hass)
        dial.set_dialled_in(40)

        switch.async_options_changed()

        assert dial.dialled_in_value is None

    def test_switch_reads_the_dial(self, make_switch, fake_hass):
        switch, dial = _day_instance(make_switch, fake_hass)

        assert switch._get_day_brightness() is None
        dial.set_dialled_in(40)
        assert switch._get_day_brightness() == 40

    def test_works_without_the_dial(self, make_switch, fake_hass):
        switch, _ = _day_instance(make_switch, fake_hass)
        del fake_hass.data[DOMAIN][switch._config_entry.entry_id]["day_brightness_number"]
        assert switch._get_day_brightness() is None
        switch._reset_day_brightness_dial()
