"""Release-hold button for DayNight Lighting.

A ``turn_on``/``turn_off`` holds the lights in place until the phase ends.
This button drops that hold early and restores the configured state, so a
visitor's deviation can be undone from the dashboard without waiting for the
next day/night transition.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.button import ButtonEntity
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
    """Set up the release-hold button from a config entry."""
    name = (
        config_entry.data.get(CONF_INSTANCE_NAME)
        or config_entry.options.get(CONF_INSTANCE_NAME)
        or "DayNight"
    )
    async_add_entities(
        [
            DayNightReleaseHoldButton(config_entry, name),
            DayNightResetBrightnessButton(config_entry, name),
        ]
    )


class DayNightResetBrightnessButton(ButtonEntity):
    """Press to drop a dialled-in brightness, back to the configured value.

    A dim press moves the brightness dial without creating a hold, so the
    release-hold button has nothing to reset. This button undoes that dim:
    the dial falls back to the configured value and the mode is re-applied.
    """

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_name = "Reset brightness"
    _attr_icon = "mdi:brightness-auto"

    def __init__(self, config_entry: ConfigEntry, name: str) -> None:
        """Initialize the button."""
        self._config_entry = config_entry
        self._instance_name = name
        self._attr_unique_id = f"{config_entry.entry_id}-reset_brightness"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, config_entry.entry_id)},
            name=f"DayNight Lighting {name}",
        )

    @property
    def _main_switch(self) -> Any | None:
        """Return the main switch of this instance, None before setup."""
        return instance_entity(self.hass, self._config_entry.entry_id, KEY_MAIN_SWITCH)

    @property
    def available(self) -> bool:
        """Only pressable while a brightness dial is actually dialled in."""
        switch = self._main_switch
        if switch is None:
            return False
        return bool(switch.has_dialled_brightness())

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
        """Re-read the dial so availability follows the dim."""
        self.async_write_ha_state()

    async def async_press(self) -> None:
        """Drop the dialled-in brightness and re-apply the configured value."""
        switch = self._main_switch
        if switch is None:
            return
        switch.reset_brightness()
        _LOGGER.info("[%s] Reset brightness pressed", self._instance_name)


class DayNightReleaseHoldButton(ButtonEntity):
    """Press to drop the hold and restore the configured state."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_name = "Release hold"
    _attr_icon = "mdi:hand-back-left-off"

    def __init__(self, config_entry: ConfigEntry, name: str) -> None:
        """Initialize the button."""
        self._config_entry = config_entry
        self._instance_name = name
        self._attr_unique_id = f"{config_entry.entry_id}-release_hold"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, config_entry.entry_id)},
            name=f"DayNight Lighting {name}",
        )

    @property
    def _main_switch(self) -> Any | None:
        """Return the main switch of this instance, None before setup."""
        return instance_entity(self.hass, self._config_entry.entry_id, KEY_MAIN_SWITCH)

    @property
    def available(self) -> bool:
        """Only pressable while something is actually held."""
        switch = self._main_switch
        if switch is None:
            return False
        return bool(switch.get_held_lights())

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
        """Re-read the held state so availability follows the hold."""
        self.async_write_ha_state()

    async def async_press(self) -> None:
        """Drop the hold and restore the configured state."""
        switch = self._main_switch
        if switch is None:
            return
        switch.release_hold()
        _LOGGER.info("[%s] Release hold pressed", self._instance_name)
