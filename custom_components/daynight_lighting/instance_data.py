"""Per-instance runtime registry in ``hass.data``.

The entities of one instance are set up by different platforms, so they find
each other through ``hass.data[DOMAIN][entry_id]``. The keys and accessors
below are the only place where that layout is spelled out.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .const import DOMAIN

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

KEY_MAIN_SWITCH = "main_switch"
KEY_CONTROL_BRIGHTNESS = "control_brightness_switch"
KEY_CONTROL_COLOR = "control_color_switch"
KEY_BLOCK_WALL_BUTTONS = "block_wall_buttons_switch"
KEY_NIGHT_BRIGHTNESS = "night_brightness_number"
KEY_DAY_BRIGHTNESS = "day_brightness_number"


def instance_data(hass: HomeAssistant, entry_id: str) -> dict[str, Any]:
    """Runtime data of one instance, empty if it is not set up."""
    return hass.data.get(DOMAIN, {}).get(entry_id, {})


def instance_entity(hass: HomeAssistant, entry_id: str, key: str) -> Any | None:
    """One entity of an instance, None before its platform set it up."""
    return instance_data(hass, entry_id).get(key)


def is_entity_on(entity: Any | None, *, default: bool) -> bool:
    """State of a toggle entity, *default* while it does not exist yet."""
    if entity is None:
        return default
    return bool(entity.is_on)
