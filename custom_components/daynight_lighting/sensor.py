"""Monitoring sensors for DayNight Lighting.

The integration decides a lot that used to be visible only in debug logs:
which mode a room is in and which values it asks its lights for. These
sensors expose that as entity state, which is what Home Assistant records,
draws in the history and keeps as long-term statistics.

The sensors never drive the integration. They mirror what the main switch
reports and are pushed updates through a dispatcher signal, so no reading
here can influence lighting behaviour.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_INSTANCE_NAME,
    DOMAIN,
    MODE_DAY,
    MODE_NIGHT,
    MODE_SLEEP,
    MODE_WAKEUP,
    SIGNAL_MONITOR_UPDATE,
)
from .instance_data import KEY_MAIN_SWITCH, instance_entity

_LOGGER = logging.getLogger(__name__)

MODE_OPTIONS = [MODE_DAY, MODE_NIGHT, MODE_SLEEP, MODE_WAKEUP]


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the monitoring sensors from a config entry."""
    name = (
        config_entry.data.get(CONF_INSTANCE_NAME)
        or config_entry.options.get(CONF_INSTANCE_NAME)
        or "DayNight"
    )

    async_add_entities(
        [
            DayNightModeSensor(config_entry, name),
            DayNightTargetBrightnessSensor(config_entry, name),
            DayNightTargetKelvinSensor(config_entry, name),
            DayNightModeProgressSensor(config_entry, name),
            DayNightLightsControlledSensor(config_entry, name),
            DayNightMotionSensorsSensor(config_entry, name),
            DayNightIlluminanceSensorsSensor(config_entry, name),
            DayNightLuxSensor(config_entry, name),
        ]
    )


class _DayNightMonitorSensor(SensorEntity):
    """Base for sensors that mirror the state of one instance."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, config_entry: ConfigEntry, name: str, key: str) -> None:
        """Initialize the sensor.

        Args:
            config_entry: Config entry of the instance being monitored
            name: Instance name, used for the device
            key: Suffix for the unique id
        """
        self._config_entry = config_entry
        self._attr_unique_id = f"{config_entry.entry_id}-{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, config_entry.entry_id)},
            name=f"DayNight Lighting {name}",
        )

    @property
    def _main_switch(self) -> Any | None:
        """Return the main switch of this instance, None before setup."""
        return instance_entity(self.hass, self._config_entry.entry_id, KEY_MAIN_SWITCH)

    async def async_added_to_hass(self) -> None:
        """Subscribe to this instance's monitor signal."""
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_MONITOR_UPDATE.format(entry_id=self._config_entry.entry_id),
                self._handle_update,
            )
        )

    @callback
    def _handle_update(self) -> None:
        """Re-read the mirrored value."""
        self.async_write_ha_state()


class DayNightModeSensor(_DayNightMonitorSensor):
    """Which mode the instance is currently in."""

    _attr_name = "Mode"
    _attr_icon = "mdi:theme-light-dark"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = MODE_OPTIONS

    def __init__(self, config_entry: ConfigEntry, name: str) -> None:
        super().__init__(config_entry, name, "mode")

    @property
    def native_value(self) -> str | None:
        switch = self._main_switch
        if switch is None:
            return None
        return switch.get_active_mode()


class DayNightTargetBrightnessSensor(_DayNightMonitorSensor):
    """Brightness the instance last asked its lights for."""

    _attr_name = "Target brightness"
    _attr_icon = "mdi:brightness-6"
    _attr_native_unit_of_measurement = "%"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, config_entry: ConfigEntry, name: str) -> None:
        super().__init__(config_entry, name, "target_brightness")

    @property
    def native_value(self) -> int | None:
        switch = self._main_switch
        if switch is None:
            return None
        target = switch.get_last_applied_target()
        if target is None:
            return None
        # Lights commanded off are at zero, not "no value"
        if not target.on:
            return 0
        return target.brightness_pct


class DayNightTargetKelvinSensor(_DayNightMonitorSensor):
    """Colour temperature the instance last asked its lights for.

    Deliberately carries no device class: Home Assistant would treat a
    temperature sensor in Kelvin as a thermometer and convert it to the
    configured unit.
    """

    _attr_name = "Target color temperature"
    _attr_icon = "mdi:thermometer"
    _attr_native_unit_of_measurement = "K"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, config_entry: ConfigEntry, name: str) -> None:
        super().__init__(config_entry, name, "target_kelvin")

    @property
    def native_value(self) -> int | None:
        switch = self._main_switch
        if switch is None:
            return None
        target = switch.get_last_applied_target()
        if target is None or not target.on:
            return None
        return target.kelvin


class DayNightModeProgressSensor(_DayNightMonitorSensor):
    """How far the sleep or wake-up ramp has run.

    Stays unknown outside those modes rather than reporting zero, which
    would drag down the statistics of the ramps.
    """

    _attr_name = "Mode progress"
    _attr_icon = "mdi:progress-clock"
    _attr_native_unit_of_measurement = "%"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, config_entry: ConfigEntry, name: str) -> None:
        super().__init__(config_entry, name, "mode_progress")

    @property
    def native_value(self) -> int | None:
        switch = self._main_switch
        if switch is None:
            return None
        progress = switch.get_mode_progress()
        if progress is None:
            return None
        return round(progress * 100)


class DayNightLightsControlledSensor(_DayNightMonitorSensor):
    """How many lights this instance currently manages."""

    _attr_name = "Lights controlled"
    _attr_icon = "mdi:lightbulb-group"

    def __init__(self, config_entry: ConfigEntry, name: str) -> None:
        super().__init__(config_entry, name, "lights_controlled")

    @property
    def native_value(self) -> int | None:
        switch = self._main_switch
        if switch is None:
            return None
        return len(switch.get_controlled_lights())

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        switch = self._main_switch
        if switch is None:
            return {}
        discovery = switch.get_discovery_info()
        if not discovery:
            # Manual instance: no area, just the configured lights.
            return {"lights": switch.get_controlled_lights()}
        return {
            "lights": discovery["controlled_lights"],
            "area": discovery["area_name"],
            "area_id": discovery["area_id"],
            "area_lights_total": len(discovery["lights_in_area"]),
            "included_lights": discovery["included_lights"],
        }


class DayNightMotionSensorsSensor(_DayNightMonitorSensor):
    """How many motion/presence sensors this instance found."""

    _attr_name = "Motion sensors"
    _attr_icon = "mdi:motion-sensor"

    def __init__(self, config_entry: ConfigEntry, name: str) -> None:
        super().__init__(config_entry, name, "motion_sensors")

    @property
    def native_value(self) -> int | None:
        switch = self._main_switch
        if switch is None:
            return None
        return len(switch.get_motion_sensor_entities())

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        switch = self._main_switch
        if switch is None:
            return {}
        return {
            "sensors": switch.get_motion_sensor_entities(),
            "active": switch.get_active_motion_sensors(),
        }


class DayNightIlluminanceSensorsSensor(_DayNightMonitorSensor):
    """How many illuminance (LUX) sensors this instance found."""

    _attr_name = "Illuminance sensors"
    _attr_icon = "mdi:brightness-6"

    def __init__(self, config_entry: ConfigEntry, name: str) -> None:
        super().__init__(config_entry, name, "illuminance_sensors")

    @property
    def native_value(self) -> int | None:
        switch = self._main_switch
        if switch is None:
            return None
        return len(switch.get_lux_reading()["sensors"])

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        switch = self._main_switch
        if switch is None:
            return {}
        return {"sensors": switch.get_lux_reading()["sensors"]}


class DayNightLuxSensor(_DayNightMonitorSensor):
    """The raw LUX reading day mode is fed with.

    The state is the raw sensor reading; ``compensated`` in the attributes is
    the ambient value day mode compares against ``lux_on``/``lux_off``, after
    subtracting the estimated lamp contribution. Read-only on purpose — the
    smoothed value feeds a rolling buffer that a monitor sensor must not touch.
    """

    _attr_name = "Lux"
    _attr_icon = "mdi:white-balance-sunny"
    _attr_device_class = SensorDeviceClass.ILLUMINANCE
    _attr_native_unit_of_measurement = "lx"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, config_entry: ConfigEntry, name: str) -> None:
        super().__init__(config_entry, name, "lux")

    @property
    def native_value(self) -> float | None:
        switch = self._main_switch
        if switch is None:
            return None
        return switch.get_lux_reading()["raw"]

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        switch = self._main_switch
        if switch is None:
            return {}
        reading = switch.get_lux_reading()
        return {
            "compensated": reading["compensated"],
            "calibrated": reading["calibrated"],
            "lamp_contrib_lux": reading["lamp_contrib_lux"],
            "last_applied_brightness_pct": reading["last_applied_brightness_pct"],
            "sensors": reading["sensors"],
        }
