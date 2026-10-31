"""Binary sensors for DayNight Lighting.

Two mirrors of the instance, so a dashboard or automation can see what the
integration is doing without influencing it:

* ``on_hold`` — ON while at least one light is held (a visitor's override or
  a detected external change).
* ``motion`` — ON while motion/presence is present, as the integration sees
  it across all configured/discovered sensors.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_INSTANCE_NAME, DOMAIN, SIGNAL_MONITOR_UPDATE
from .instance_data import KEY_MAIN_SWITCH, instance_entity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the instance's binary sensors from a config entry."""
    name = (
        config_entry.data.get(CONF_INSTANCE_NAME)
        or config_entry.options.get(CONF_INSTANCE_NAME)
        or "DayNight"
    )
    async_add_entities(
        [
            DayNightHoldSensor(config_entry, name),
            DayNightMotionSensor(config_entry, name),
        ]
    )


class _DayNightBinarySensor(BinarySensorEntity):
    """Base for binary sensors that mirror one instance."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, config_entry: ConfigEntry, name: str, key: str) -> None:
        """Initialize the sensor."""
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


class DayNightHoldSensor(_DayNightBinarySensor):
    """ON while a service holds the lights in place (visitor override)."""

    _attr_name = "On hold"
    _attr_icon = "mdi:hand-back-left"

    def __init__(self, config_entry: ConfigEntry, name: str) -> None:
        super().__init__(config_entry, name, "hold")

    @property
    def is_on(self) -> bool:
        """ON while at least one light is held."""
        switch = self._main_switch
        if switch is None:
            return False
        return bool(switch.get_held_lights())

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Per-light hold reasons (``detected``/``service``)."""
        switch = self._main_switch
        if switch is None:
            return {}
        return {"lights": switch.get_held_lights_with_reasons()}


class DayNightMotionSensor(_DayNightBinarySensor):
    """ON while motion/presence is present, across all sensors."""

    _attr_name = "Motion"
    _attr_icon = "mdi:motion-sensor"

    def __init__(self, config_entry: ConfigEntry, name: str) -> None:
        super().__init__(config_entry, name, "motion")

    @property
    def is_on(self) -> bool:
        """ON while any motion/presence sensor is active."""
        switch = self._main_switch
        if switch is None:
            return False
        return switch.get_motion_now()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """The sensors, and which of them are currently active."""
        switch = self._main_switch
        if switch is None:
            return {}
        return {
            "sensors": switch.get_motion_sensor_entities(),
            "active": switch.get_active_motion_sensors(),
        }
