"""DayNight Lighting integration for Home Assistant."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .instance_data import KEY_MAIN_SWITCH, instance_entity
from .services import (
    ADJUST_BRIGHTNESS_SCHEMA,
    CALIBRATE_LUX_SCHEMA,
    HOLD_ALL_SCHEMA,
    RELEASE_HOLD_SCHEMA,
    RESET_DAY_BRIGHTNESS_SCHEMA,
    RESET_NIGHT_BRIGHTNESS_SCHEMA,
    START_SLEEP_MODE_SCHEMA,
    START_WAKEUP_MODE_SCHEMA,
    STOP_SLEEP_MODE_SCHEMA,
    STOP_WAKEUP_MODE_SCHEMA,
    TURN_OFF_SCHEMA,
    TURN_ON_SCHEMA,
    async_adjust_brightness,
    async_calibrate_lux,
    async_hold_all,
    async_release_hold,
    async_reset_day_brightness,
    async_reset_night_brightness,
    async_start_sleep_mode,
    async_start_wakeup_mode,
    async_stop_sleep_mode,
    async_stop_wakeup_mode,
    async_turn_off,
    async_turn_on,
)

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["switch", "sensor", "number", "button", "binary_sensor"]


async def async_setup(hass: HomeAssistant, config: dict[str, Any]) -> bool:
    """Set up the component (YAML not used; config flow only)."""
    hass.services.async_register(
        DOMAIN,
        "turn_on",
        async_turn_on,
        schema=TURN_ON_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        "turn_off",
        async_turn_off,
        schema=TURN_OFF_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        "calibrate_lux",
        async_calibrate_lux,
        schema=CALIBRATE_LUX_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        "start_sleep_mode",
        async_start_sleep_mode,
        schema=START_SLEEP_MODE_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        "start_wakeup_mode",
        async_start_wakeup_mode,
        schema=START_WAKEUP_MODE_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        "stop_sleep_mode",
        async_stop_sleep_mode,
        schema=STOP_SLEEP_MODE_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        "stop_wakeup_mode",
        async_stop_wakeup_mode,
        schema=STOP_WAKEUP_MODE_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        "adjust_brightness",
        async_adjust_brightness,
        schema=ADJUST_BRIGHTNESS_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        "reset_night_brightness",
        async_reset_night_brightness,
        schema=RESET_NIGHT_BRIGHTNESS_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        "reset_day_brightness",
        async_reset_day_brightness,
        schema=RESET_DAY_BRIGHTNESS_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        "release_hold",
        async_release_hold,
        schema=RELEASE_HOLD_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        "hold_all",
        async_hold_all,
        schema=HOLD_ALL_SCHEMA,
    )
    return True


async def async_setup_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Set up DayNight Lighting from a config entry."""
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][config_entry.entry_id] = {}

    await hass.config_entries.async_forward_entry_setups(config_entry, PLATFORMS)

    # Re-create helper instances when options are changed in the UI so the
    # running switch picks up the new configuration immediately.
    config_entry.async_on_unload(
        config_entry.add_update_listener(_async_options_updated)
    )
    return True


async def _async_options_updated(
    hass: HomeAssistant, config_entry: ConfigEntry
) -> None:
    """Called when the user saves new options in the UI."""
    main_switch = instance_entity(hass, config_entry.entry_id, KEY_MAIN_SWITCH)
    if main_switch is not None:
        main_switch.async_options_changed()
        _LOGGER.debug(
            "[%s] Options updated, restarted listeners",
            config_entry.title,
        )


async def async_unload_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(
        config_entry,
        PLATFORMS,
    )
    if unload_ok and DOMAIN in hass.data:
        hass.data[DOMAIN].pop(config_entry.entry_id, None)
        if not hass.data[DOMAIN]:
            del hass.data[DOMAIN]
    return unload_ok
