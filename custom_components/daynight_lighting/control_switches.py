"""Auxiliary switches of a DayNight Lighting instance.

* **DayNightLightingControlBrightnessSwitch** – when OFF brightness adjustments are skipped
* **DayNightLightingControlColorSwitch** – when OFF colour adjustments are skipped
* **DayNightLightingBlockWallButtonsSwitch** – the "safety room": when ON our services
  (turn_on, turn_off, adjust_brightness) are ignored at night in a motion-lit room,
  and held lights are overridden by the configured defaults (see ``exclude_held``)

Each of them owns its state; the main switch and the mode handlers only read it.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_ON
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.restore_state import RestoreEntity

from .const import (
    CONF_INSTANCE_NAME,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


def _instance_name(config_entry: ConfigEntry) -> str:
    return (
        config_entry.data.get(CONF_INSTANCE_NAME)
        or config_entry.options.get(CONF_INSTANCE_NAME)
        or "DayNight"
    )


class _InstanceSwitch(SwitchEntity, RestoreEntity):
    """A switch that belongs to the device of one instance."""

    _attr_has_entity_name = True

    def __init__(
        self, config_entry: ConfigEntry, key: str, *, initial: bool
    ) -> None:
        self._config_entry = config_entry
        self._instance_name = _instance_name(config_entry)
        self._attr_unique_id = f"{config_entry.entry_id}-{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, config_entry.entry_id)},
            name=f"DayNight Lighting {self._instance_name}",
        )
        self._attr_is_on = initial

    @property
    def unique_id(self) -> str:
        return self._attr_unique_id

    @property
    def is_on(self) -> bool:
        return self._attr_is_on


# ===================================================================
#  Control Brightness / Control Color Switches
# ===================================================================

class _ControlAttributeSwitch(_InstanceSwitch):
    """A plain toggle that owns its state; handlers only read it."""

    def __init__(self, config_entry: ConfigEntry, key: str, *, initial: bool = True) -> None:
        super().__init__(config_entry, key, initial=initial)

    async def async_turn_on(self, **kwargs: Any) -> None:
        self._attr_is_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        self._attr_is_on = False
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if (last_state := await self.async_get_last_state()) is not None:
            self._attr_is_on = last_state.state == STATE_ON


class DayNightLightingControlBrightnessSwitch(_ControlAttributeSwitch):
    """When OFF the integration skips brightness adjustments."""

    _attr_name = "Control Brightness"

    def __init__(self, config_entry: ConfigEntry) -> None:
        super().__init__(config_entry, "control_brightness")


class DayNightLightingControlColorSwitch(_ControlAttributeSwitch):
    """When OFF the integration skips colour adjustments."""

    _attr_name = "Control Color"

    def __init__(self, config_entry: ConfigEntry) -> None:
        super().__init__(config_entry, "control_color")


class DayNightLightingBlockWallButtonsSwitch(_ControlAttributeSwitch):
    """The safety room: ignores wall buttons and enforces defaults at night.

    Safety for a motion-lit room like a staircase: a visitor's button presses
    (turn_on, turn_off, dim) are ignored, so motion alone decides and the room
    can never be switched off by accident. At the same time the configured
    defaults are enforced on every light — even the ones a service holds — so
    an external intervention cannot keep the room dark. Default off; set it
    once per instance.
    """

    _attr_name = "Safety room"
    _attr_icon = "mdi:toggle-switch-off-outline"

    def __init__(self, config_entry: ConfigEntry) -> None:
        super().__init__(config_entry, "block_wall_buttons", initial=False)
