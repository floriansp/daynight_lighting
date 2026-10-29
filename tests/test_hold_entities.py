"""Tests for the release-hold button and the on-hold binary sensor.

The button gives the dashboard a way to drop a hold, and the sensor shows
whether a hold is currently in effect. Both mirror the main switch through
the monitor signal, so they never influence lighting behaviour.
"""

from __future__ import annotations

import pytest

from custom_components.daynight_lighting.binary_sensor import (
    DayNightHoldSensor,
    DayNightMotionSensor,
    async_setup_entry as binary_setup,
)
from custom_components.daynight_lighting.button import (
    DayNightReleaseHoldButton,
    DayNightResetBrightnessButton,
    async_setup_entry as button_setup,
)
from custom_components.daynight_lighting.const import DOMAIN


async def _attach(entity, fake_hass):
    """Put an entity into hass and subscribe it, like the platform would."""
    entity.hass = fake_hass
    writes: list[int] = []
    entity.async_write_ha_state = lambda: writes.append(1)
    await entity.async_added_to_hass()
    return writes


def _make_instance(make_switch, fake_hass):
    """Create a switch registered as main_switch, like setup does."""
    switch, *_ = make_switch()
    fake_hass.data[DOMAIN][switch._config_entry.entry_id]["main_switch"] = switch
    return switch, switch._config_entry


class TestButtonSetup:
    """The button platform exposes the hold and reset buttons per instance."""

    @pytest.mark.asyncio
    async def test_adds_both_buttons(self, fake_hass, fake_store, make_switch):
        _, entry = _make_instance(make_switch, fake_hass)
        added = []

        await button_setup(fake_hass, entry, lambda entities: added.extend(entities))

        assert [type(b) for b in added] == [
            DayNightReleaseHoldButton,
            DayNightResetBrightnessButton,
        ]
        assert {b.unique_id for b in added} == {
            "test_entry-release_hold",
            "test_entry-reset_brightness",
        }


class TestSensorSetup:
    """The binary sensor platform exposes two sensors per instance."""

    @pytest.mark.asyncio
    async def test_adds_both_sensors(self, fake_hass, fake_store, make_switch):
        _, entry = _make_instance(make_switch, fake_hass)
        added = []

        await binary_setup(fake_hass, entry, lambda entities: added.extend(entities))

        assert [type(s) for s in added] == [DayNightHoldSensor, DayNightMotionSensor]
        assert {s.unique_id for s in added} == {"test_entry-hold", "test_entry-motion"}


class TestHoldSensorValue:
    """The sensor is ON while at least one light is held."""

    def test_off_without_a_hold(self, make_switch, fake_hass):
        switch, entry = _make_instance(make_switch, fake_hass)
        sensor = DayNightHoldSensor(entry, "Test")
        sensor.hass = fake_hass

        assert sensor.is_on is False

    def test_on_while_a_light_is_held(self, make_switch, fake_hass):
        switch, entry = _make_instance(make_switch, fake_hass)
        switch._state_ctrl.set_hold(["light.a"])
        sensor = DayNightHoldSensor(entry, "Test")
        sensor.hass = fake_hass

        assert sensor.is_on is True

    def test_off_without_a_main_switch(self, make_switch, fake_hass):
        _, entry = _make_instance(make_switch, fake_hass)
        del fake_hass.data[DOMAIN][entry.entry_id]["main_switch"]
        sensor = DayNightHoldSensor(entry, "Test")
        sensor.hass = fake_hass

        assert sensor.is_on is False


class TestHoldSensorPush:
    """The sensor is pushed, it never polls the instance."""

    def test_sensor_does_not_poll(self, make_switch, fake_hass):
        _, entry = _make_instance(make_switch, fake_hass)
        assert DayNightHoldSensor(entry, "Test").should_poll is False

    @pytest.mark.asyncio
    async def test_holding_a_light_updates_the_sensor(self, make_switch, fake_hass):
        switch, entry = _make_instance(make_switch, fake_hass)
        sensor = DayNightHoldSensor(entry, "Test")
        writes = await _attach(sensor, fake_hass)

        switch.record_lights_turned_on_by_service(["light.a"])

        assert writes, "sensor was not notified"
        assert sensor.is_on is True

    @pytest.mark.asyncio
    async def test_releasing_the_hold_updates_the_sensor(self, make_switch, fake_hass):
        switch, entry = _make_instance(make_switch, fake_hass)
        switch._state_ctrl.set_hold(["light.a"])
        sensor = DayNightHoldSensor(entry, "Test")
        writes = await _attach(sensor, fake_hass)

        switch.release_hold()

        assert writes, "sensor was not notified"
        assert sensor.is_on is False


class TestMotionSensorValue:
    """The motion sensor is ON while motion is present, as the instance sees it."""

    def test_off_without_motion(self, make_switch, fake_hass):
        switch, entry = _make_instance(make_switch, fake_hass)
        sensor = DayNightMotionSensor(entry, "Test")
        sensor.hass = fake_hass

        assert sensor.is_on is False

    def test_on_while_motion_is_present(self, make_switch, fake_hass):
        switch, entry = _make_instance(make_switch, fake_hass)
        from tests.conftest import FakeState

        fake_hass.states.set("binary_sensor.motion", FakeState(state="on"))
        sensor = DayNightMotionSensor(entry, "Test")
        sensor.hass = fake_hass

        assert sensor.is_on is True
        assert sensor.extra_state_attributes["active"] == ["binary_sensor.motion"]

    def test_off_without_a_main_switch(self, make_switch, fake_hass):
        _, entry = _make_instance(make_switch, fake_hass)
        del fake_hass.data[DOMAIN][entry.entry_id]["main_switch"]
        sensor = DayNightMotionSensor(entry, "Test")
        sensor.hass = fake_hass

        assert sensor.is_on is False

    def test_sensor_does_not_poll(self, make_switch, fake_hass):
        _, entry = _make_instance(make_switch, fake_hass)
        assert DayNightMotionSensor(entry, "Test").should_poll is False


class TestReleaseHoldButton:
    """Pressing the button drops the hold and restores the configured state."""

    def test_unavailable_without_a_hold(self, make_switch, fake_hass):
        switch, entry = _make_instance(make_switch, fake_hass)
        button = DayNightReleaseHoldButton(entry, "Test")
        button.hass = fake_hass

        assert button.available is False

    def test_available_while_a_light_is_held(self, make_switch, fake_hass):
        switch, entry = _make_instance(make_switch, fake_hass)
        switch._state_ctrl.set_hold(["light.a"])
        button = DayNightReleaseHoldButton(entry, "Test")
        button.hass = fake_hass

        assert button.available is True

    @pytest.mark.asyncio
    async def test_press_clears_the_hold(self, make_switch, fake_hass):
        switch, entry = _make_instance(make_switch, fake_hass)
        switch._state_ctrl.set_hold(["light.a"])
        button = DayNightReleaseHoldButton(entry, "Test")
        button.hass = fake_hass
        await button.async_added_to_hass()

        await button.async_press()

        assert switch._state_ctrl.get_held_lights() == set()

    @pytest.mark.asyncio
    async def test_hold_change_updates_availability(self, make_switch, fake_hass):
        switch, entry = _make_instance(make_switch, fake_hass)
        button = DayNightReleaseHoldButton(entry, "Test")
        await _attach(button, fake_hass)

        assert button.available is False
        switch._state_ctrl.set_hold(["light.a"])

        assert button.available is True


class TestResetBrightnessButton:
    """The button drops a dialled-in brightness back to the configured value."""

    @staticmethod
    def _force_night(switch):
        from custom_components.daynight_lighting.const import MODE_NIGHT

        class _Provider:
            def get_current_mode(self) -> str:
                return MODE_NIGHT

        switch._schedule_override = _Provider()

    @staticmethod
    def _add_night_dial(switch, fake_hass):
        from custom_components.daynight_lighting.instance_data import (
            KEY_NIGHT_BRIGHTNESS,
        )
        from custom_components.daynight_lighting.number import (
            DayNightNightBrightnessNumber,
        )

        dial = DayNightNightBrightnessNumber(switch._config_entry, "Test")
        dial.hass = fake_hass
        dial.async_write_ha_state = lambda: None
        fake_hass.data[DOMAIN][switch._config_entry.entry_id][KEY_NIGHT_BRIGHTNESS] = dial
        return dial

    def test_unavailable_without_a_dim(self, make_switch, fake_hass):
        switch, entry = _make_instance(make_switch, fake_hass)
        button = DayNightResetBrightnessButton(entry, "Test")
        button.hass = fake_hass

        assert button.available is False

    def test_available_while_dimmed(self, make_switch, fake_hass):
        switch, entry = _make_instance(make_switch, fake_hass)
        self._force_night(switch)
        dial = self._add_night_dial(switch, fake_hass)
        dial.set_dialled_in(50)
        button = DayNightResetBrightnessButton(entry, "Test")
        button.hass = fake_hass

        assert button.available is True

    @pytest.mark.asyncio
    async def test_press_resets_the_dial(self, make_switch, fake_hass):
        switch, entry = _make_instance(make_switch, fake_hass)
        self._force_night(switch)
        dial = self._add_night_dial(switch, fake_hass)
        dial.set_dialled_in(50)
        button = DayNightResetBrightnessButton(entry, "Test")
        button.hass = fake_hass
        await button.async_added_to_hass()

        await button.async_press()

        assert dial.dialled_in_value is None
        assert dial.native_value == 80  # configured default

    @pytest.mark.asyncio
    async def test_dim_change_updates_availability(self, make_switch, fake_hass):
        switch, entry = _make_instance(make_switch, fake_hass)
        self._force_night(switch)
        self._add_night_dial(switch, fake_hass)
        button = DayNightResetBrightnessButton(entry, "Test")
        writes = await _attach(button, fake_hass)

        assert button.available is False
        switch.adjust_brightness(-10)

        assert button.available is True
        assert writes, "dimming must push the button's availability"
