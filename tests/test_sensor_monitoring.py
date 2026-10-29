"""Tests for the monitoring sensors.

The sensors must mirror the instance without ever influencing it, so the
tests cover both the values they report and the push path that updates
them.
"""

from __future__ import annotations

import pytest

from custom_components.daynight_lighting.const import (
    DOMAIN,
    EVENT_MODE_CHANGED,
    MODE_DAY,
    MODE_NIGHT,
    MODE_SLEEP,
)
from custom_components.daynight_lighting.manual_control import ExpectedState
from custom_components.daynight_lighting.sensor import (
    DayNightIlluminanceSensorsSensor,
    DayNightLightsControlledSensor,
    DayNightLuxSensor,
    DayNightModeProgressSensor,
    DayNightModeSensor,
    DayNightMotionSensorsSensor,
    DayNightTargetBrightnessSensor,
    DayNightTargetKelvinSensor,
    async_setup_entry,
)

from tests.test_event_driven_detection import _make_switch_with_mocks


async def _attach(sensor, fake_hass):
    """Put a sensor into hass and subscribe it, like the platform would."""
    sensor.hass = fake_hass
    writes: list[int] = []
    sensor.async_write_ha_state = lambda: writes.append(1)
    await sensor.async_added_to_hass()
    return writes


def _make_instance(fake_hass, fake_store):
    """Create a switch that is registered as main_switch, like setup does."""
    switch, *_ = _make_switch_with_mocks(fake_hass, fake_store)
    fake_hass.data[DOMAIN][switch._config_entry.entry_id]["main_switch"] = switch
    return switch, switch._config_entry


class TestSetup:
    """The platform exposes one set of sensors per instance."""

    @pytest.mark.asyncio
    async def test_adds_all_sensors(self, fake_hass, fake_store):
        _, entry = _make_instance(fake_hass, fake_store)
        added = []

        await async_setup_entry(fake_hass, entry, lambda entities: added.extend(entities))

        assert [type(sensor) for sensor in added] == [
            DayNightModeSensor,
            DayNightTargetBrightnessSensor,
            DayNightTargetKelvinSensor,
            DayNightModeProgressSensor,
            DayNightLightsControlledSensor,
            DayNightMotionSensorsSensor,
            DayNightIlluminanceSensorsSensor,
            DayNightLuxSensor,
        ]
        assert [sensor.unique_id for sensor in added] == [
            "test_entry-mode",
            "test_entry-target_brightness",
            "test_entry-target_kelvin",
            "test_entry-mode_progress",
            "test_entry-lights_controlled",
            "test_entry-motion_sensors",
            "test_entry-illuminance_sensors",
            "test_entry-lux",
        ]


class TestReportedValues:
    """Each sensor mirrors one aspect of the instance."""

    def test_mode_follows_the_switch(self, fake_hass, fake_store):
        switch, entry = _make_instance(fake_hass, fake_store)
        switch._last_mode = MODE_DAY
        sensor = DayNightModeSensor(entry, "Test")
        sensor.hass = fake_hass

        assert sensor.native_value == switch.get_active_mode()
        assert sensor.native_value == MODE_DAY

    def test_mode_is_none_while_the_instance_is_off(self, fake_hass, fake_store):
        switch, entry = _make_instance(fake_hass, fake_store)
        switch._stop_listeners()
        sensor = DayNightModeSensor(entry, "Test")
        sensor.hass = fake_hass

        assert sensor.native_value is None

    def test_targets_mirror_the_applied_values(self, fake_hass, fake_store):
        switch, entry = _make_instance(fake_hass, fake_store)
        switch.record_applied_target(
            ExpectedState(on=True, brightness_pct=42, kelvin=3000)
        )

        brightness = DayNightTargetBrightnessSensor(entry, "Test")
        kelvin = DayNightTargetKelvinSensor(entry, "Test")
        brightness.hass = fake_hass
        kelvin.hass = fake_hass

        assert brightness.native_value == 42
        assert kelvin.native_value == 3000

    def test_lights_off_report_zero_brightness_and_no_colour(self, fake_hass, fake_store):
        switch, entry = _make_instance(fake_hass, fake_store)
        switch.record_applied_target(ExpectedState(on=False))

        brightness = DayNightTargetBrightnessSensor(entry, "Test")
        kelvin = DayNightTargetKelvinSensor(entry, "Test")
        brightness.hass = fake_hass
        kelvin.hass = fake_hass

        assert brightness.native_value == 0
        assert kelvin.native_value is None

    def test_progress_is_unknown_outside_the_ramps(self, fake_hass, fake_store):
        _, entry = _make_instance(fake_hass, fake_store)
        sensor = DayNightModeProgressSensor(entry, "Test")
        sensor.hass = fake_hass

        assert sensor.native_value is None

    def test_progress_is_a_percentage_during_sleep(self, fake_hass, fake_store):
        switch, entry = _make_instance(fake_hass, fake_store)
        switch._last_mode = MODE_SLEEP
        sleep_handler = switch._get_mode_handler(MODE_SLEEP)
        sleep_handler.get_progress = lambda: 0.423

        sensor = DayNightModeProgressSensor(entry, "Test")
        sensor.hass = fake_hass

        assert sensor.native_value == 42

    def test_values_are_none_without_a_main_switch(self, fake_hass, fake_store):
        _, entry = _make_instance(fake_hass, fake_store)
        del fake_hass.data[DOMAIN][entry.entry_id]["main_switch"]

        sensor = DayNightModeSensor(entry, "Test")
        sensor.hass = fake_hass

        assert sensor.native_value is None


class TestPushPath:
    """Sensors are updated by the instance, they never poll it."""

    def test_sensors_do_not_poll(self, fake_hass, fake_store):
        _, entry = _make_instance(fake_hass, fake_store)
        assert DayNightModeSensor(entry, "Test").should_poll is False

    @pytest.mark.asyncio
    async def test_applying_lights_updates_the_sensor(self, fake_hass, fake_store):
        """The applier reports through to the sensor without any polling."""
        switch, entry = _make_instance(fake_hass, fake_store)
        sensor = DayNightTargetBrightnessSensor(entry, "Test")
        writes = await _attach(sensor, fake_hass)

        handler = switch._get_mode_handler(MODE_DAY)
        handler._shared.light_applier.turn_on(
            ["light.a"],
            {"entity_id": ["light.a"], "brightness_pct": 55},
            transition="tick",
            brightness_pct=55,
            kelvin=4000,
        )

        assert writes, "sensor was not notified"
        assert sensor.native_value == 55

    @pytest.mark.asyncio
    async def test_mode_change_updates_the_sensor_and_fires_an_event(
        self, fake_hass, fake_store
    ):
        switch, entry = _make_instance(fake_hass, fake_store)
        sensor = DayNightModeSensor(entry, "Test")
        writes = await _attach(sensor, fake_hass)
        fake_hass.bus.fired.clear()

        switch._report_mode_change(MODE_DAY, MODE_SLEEP)

        assert writes, "sensor was not notified"
        events = fake_hass.bus.events_of_type(EVENT_MODE_CHANGED)
        assert events[-1]["from_mode"] == MODE_DAY
        assert events[-1]["to_mode"] == MODE_SLEEP
        assert events[-1]["instance"] == "Test"
        assert events[-1]["entry_id"] == "test_entry"

    @pytest.mark.asyncio
    async def test_the_push_carries_the_new_mode_not_the_old_one(
        self, fake_hass, fake_store
    ):
        """The sensor re-reads *during* the change, so the mode must be set.

        Reporting the mode we just left is not a display glitch that the next
        update repairs: in a night-with-motion room the only other thing that
        notifies the sensors is a light actually being switched, so without
        motion the wrong mode stands for hours.
        """
        switch, entry = _make_instance(fake_hass, fake_store)
        switch._last_mode = MODE_DAY
        sensor = DayNightModeSensor(entry, "Test")
        sensor.hass = fake_hass
        seen: list[str | None] = []
        sensor.async_write_ha_state = lambda: seen.append(sensor.native_value)
        await sensor.async_added_to_hass()

        switch._report_mode_change(MODE_DAY, MODE_NIGHT)

        assert seen == [MODE_NIGHT]

    def test_reporting_a_change_records_the_mode(self, fake_hass, fake_store):
        switch, _ = _make_instance(fake_hass, fake_store)
        switch._last_mode = MODE_DAY

        switch._report_mode_change(MODE_DAY, MODE_NIGHT)

        assert switch.get_active_mode() == MODE_NIGHT


class TestDiscoveryAndLiveSensors:
    """The new sensors surface what area discovery found and live readings."""

    def test_lights_controlled_counts_the_managed_lights(self, fake_hass, fake_store):
        switch, entry = _make_instance(fake_hass, fake_store)
        sensor = DayNightLightsControlledSensor(entry, "Test")
        sensor.hass = fake_hass

        assert sensor.native_value == len(switch.get_controlled_lights()) == 2

    def test_motion_sensors_reports_count_and_active(self, fake_hass, fake_store):
        switch, entry = _make_instance(fake_hass, fake_store)
        sensor = DayNightMotionSensorsSensor(entry, "Test")
        sensor.hass = fake_hass

        assert sensor.native_value == 1
        assert sensor.extra_state_attributes == {
            "sensors": ["binary_sensor.motion"],
            "active": [],
        }

    def test_illuminance_sensors_reports_count(self, fake_hass, fake_store):
        _, entry = _make_instance(fake_hass, fake_store)
        sensor = DayNightIlluminanceSensorsSensor(entry, "Test")
        sensor.hass = fake_hass

        assert sensor.native_value == 1
        assert sensor.extra_state_attributes == {"sensors": ["sensor.lux"]}

    def test_lux_reports_raw_and_compensated(self, fake_hass, fake_store):
        _, entry = _make_instance(fake_hass, fake_store)
        sensor = DayNightLuxSensor(entry, "Test")
        sensor.hass = fake_hass

        assert sensor.native_value == 50.0
        assert sensor.extra_state_attributes["compensated"] == 50.0
        assert sensor.extra_state_attributes["calibrated"] is False

    def test_values_are_none_without_a_main_switch(self, fake_hass, fake_store):
        _, entry = _make_instance(fake_hass, fake_store)
        del fake_hass.data[DOMAIN][entry.entry_id]["main_switch"]

        for sensor_cls in (
            DayNightLightsControlledSensor,
            DayNightMotionSensorsSensor,
            DayNightIlluminanceSensorsSensor,
            DayNightLuxSensor,
        ):
            sensor = sensor_cls(entry, "Test")
            sensor.hass = fake_hass
            assert sensor.native_value is None


class TestMonitoringCannotBreakControl:
    """A failing observer must not stop the lights from switching."""

    def test_observer_exception_is_contained(self, fake_hass, fake_store):
        switch, _ = _make_instance(fake_hass, fake_store)
        handler = switch._get_mode_handler(MODE_DAY)
        applier = handler._shared.light_applier
        applier._on_applied = lambda applied: 1 / 0

        applier.turn_off(["light.a"], transition="tick")

        assert switch._state_ctrl.get_expected_state("light.a")["on"] is False
