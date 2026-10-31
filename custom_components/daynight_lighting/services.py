"""Services for DayNight Lighting: turn_on / turn_off by instance entity_id."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import entity_registry as er

from .config import DayNightConfig
from .const import (
    CONF_AREA_ID,
    MAIN_SWITCH_UNIQUE_ID_SUFFIX,
)
from .instance_data import (
    KEY_DAY_BRIGHTNESS,
    KEY_MAIN_SWITCH,
    KEY_NIGHT_BRIGHTNESS,
    instance_entity,
)

_LOGGER = logging.getLogger(__name__)

ATTR_ENTITY_ID = "entity_id"


def _entity_ids_to_list(value: str | list[str] | None) -> list[str]:
    """Normalize entity_id to list (HA may pass a single string or None)."""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _get_entity_ids_from_call(call: ServiceCall) -> list[str]:
    """Get entity_id list from call (entity_id or target.entity_id for UI)."""
    entity_ids = call.data.get(ATTR_ENTITY_ID)
    if not entity_ids and call.data.get("target"):
        entity_ids = call.data["target"].get("entity_id")
    return _entity_ids_to_list(entity_ids)


# Accept entity_id (YAML/automation) or target.entity_id (UI from services.yaml)
_ENTITY_IDS_SCHEMA = vol.Any(
    vol.In([None]),
    str,
    [str],
)

TURN_ON_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_ENTITY_ID): _ENTITY_IDS_SCHEMA,
        vol.Optional("target"): vol.Schema(
            {vol.Optional("entity_id"): _ENTITY_IDS_SCHEMA},
            extra=vol.ALLOW_EXTRA,
        ),
        vol.Optional("hold"): vol.Coerce(bool),
    },
    extra=vol.ALLOW_EXTRA,
)

TURN_OFF_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_ENTITY_ID): _ENTITY_IDS_SCHEMA,
        vol.Optional("target"): vol.Schema(
            {vol.Optional("entity_id"): _ENTITY_IDS_SCHEMA},
            extra=vol.ALLOW_EXTRA,
        ),
        vol.Optional("hold"): vol.Coerce(bool),
    },
    extra=vol.ALLOW_EXTRA,
)

CALIBRATE_LUX_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_ENTITY_ID): _ENTITY_IDS_SCHEMA,
    },
    extra=vol.ALLOW_EXTRA,
)

START_SLEEP_MODE_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_ENTITY_ID): _ENTITY_IDS_SCHEMA,
        vol.Optional("target"): vol.Schema(
            {vol.Optional("entity_id"): _ENTITY_IDS_SCHEMA},
            extra=vol.ALLOW_EXTRA,
        ),
        vol.Optional("duration_min"): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=240)
        ),
        vol.Optional("brightness_pct"): vol.All(
            vol.Coerce(int), vol.Range(min=0, max=100)
        ),
        vol.Optional("color_temp_kelvin"): vol.All(
            vol.Coerce(int), vol.Range(min=1000, max=10000)
        ),
    },
    extra=vol.ALLOW_EXTRA,
)

START_WAKEUP_MODE_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_ENTITY_ID): _ENTITY_IDS_SCHEMA,
        vol.Optional("target"): vol.Schema(
            {vol.Optional("entity_id"): _ENTITY_IDS_SCHEMA},
            extra=vol.ALLOW_EXTRA,
        ),
        vol.Optional("duration_min"): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=240)
        ),
        vol.Optional("start_brightness_pct"): vol.All(
            vol.Coerce(int), vol.Range(min=0, max=100)
        ),
        vol.Optional("end_brightness_pct"): vol.All(
            vol.Coerce(int), vol.Range(min=0, max=100)
        ),
        vol.Optional("color_temp_kelvin"): vol.All(
            vol.Coerce(int), vol.Range(min=1000, max=10000)
        ),
    },
    extra=vol.ALLOW_EXTRA,
)

STOP_SLEEP_MODE_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_ENTITY_ID): _ENTITY_IDS_SCHEMA,
        vol.Optional("target"): vol.Schema(
            {vol.Optional("entity_id"): _ENTITY_IDS_SCHEMA},
            extra=vol.ALLOW_EXTRA,
        ),
    },
    extra=vol.ALLOW_EXTRA,
)

STOP_WAKEUP_MODE_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_ENTITY_ID): _ENTITY_IDS_SCHEMA,
        vol.Optional("target"): vol.Schema(
            {vol.Optional("entity_id"): _ENTITY_IDS_SCHEMA},
            extra=vol.ALLOW_EXTRA,
        ),
    },
    extra=vol.ALLOW_EXTRA,
)

ADJUST_BRIGHTNESS_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_ENTITY_ID): _ENTITY_IDS_SCHEMA,
        vol.Optional("target"): vol.Schema(
            {vol.Optional("entity_id"): _ENTITY_IDS_SCHEMA},
            extra=vol.ALLOW_EXTRA,
        ),
        vol.Required("step"): vol.All(vol.Coerce(int), vol.Range(min=-100, max=100)),
    },
    extra=vol.ALLOW_EXTRA,
)

RESET_NIGHT_BRIGHTNESS_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_ENTITY_ID): _ENTITY_IDS_SCHEMA,
        vol.Optional("target"): vol.Schema(
            {vol.Optional("entity_id"): _ENTITY_IDS_SCHEMA},
            extra=vol.ALLOW_EXTRA,
        ),
    },
    extra=vol.ALLOW_EXTRA,
)


RESET_DAY_BRIGHTNESS_SCHEMA = RESET_NIGHT_BRIGHTNESS_SCHEMA

RELEASE_HOLD_SCHEMA = RESET_NIGHT_BRIGHTNESS_SCHEMA

HOLD_ALL_SCHEMA = RESET_NIGHT_BRIGHTNESS_SCHEMA


# Keys that make turn_on an explicit instruction, recorded as our own values
_BRIGHTNESS_KEYS = ("brightness_pct", "brightness")
_COLOR_KEYS = ("color_temp_kelvin", "color_temp", "rgb_color")


def _user_passed_brightness_or_color(data: dict[str, Any]) -> bool:
    """True if data contains any brightness or color attribute."""
    return (
        any(data.get(k) is not None for k in _BRIGHTNESS_KEYS)
        or any(data.get(k) is not None for k in _COLOR_KEYS)
    )


def _get_config_and_lights_for_entity_id(
    hass: HomeAssistant, entity_id: str
) -> tuple[ConfigEntry | None, list[str]]:
    """
    Resolve a DayNight Lighting main switch entity_id to its config entry and lights.
    Returns (config_entry, lights) or (None, []).
    """
    registry = er.async_get(hass)
    entity = registry.async_get(entity_id)
    if not entity or not entity.unique_id:
        return (None, [])
    if not entity.unique_id.endswith(MAIN_SWITCH_UNIQUE_ID_SUFFIX):
        return (None, [])
    entry_id = entity.unique_id[: -len(MAIN_SWITCH_UNIQUE_ID_SUFFIX)]
    config_entry = hass.config_entries.async_get_entry(entry_id)
    if not config_entry or config_entry.state is not ConfigEntryState.LOADED:
        return (None, [])
    # Resolve the lights the instance controls: legacy list, explicit
    # included_lights, or — with area discovery and none chosen — every real
    # (non-group) light in the area.
    cfg = DayNightConfig.from_ha_options(
        config_entry.options,
        data_area_id=config_entry.data.get(CONF_AREA_ID),
    )
    lights = cfg.get_effective_lights(hass)
    return (config_entry, lights)


def _get_lights_for_entity_id(hass: HomeAssistant, entity_id: str) -> list[str] | None:
    """Resolve entity_id to lights list; None if not a valid main switch."""
    config_entry, lights = _get_config_and_lights_for_entity_id(hass, entity_id)
    return lights if config_entry else None


# Keys to strip from service data before forwarding to light.turn_on / turn_off.
# "keep_on_in_night_mode" is the removed pre-1.19.0 parameter that old
# wall-button automations still send alongside ``hold: true``. It is redundant
# now, but must be dropped here — forwarding it to ``light.turn_on`` makes the
# call fail with "not a valid option", so the wall button stops switching.
_SERVICE_STRIP_KEYS = (ATTR_ENTITY_ID, "target", "hold", "keep_on_in_night_mode")


async def async_turn_on(call: ServiceCall) -> None:
    """Turn on lights of the given DayNight Lighting instance(s)."""
    hass = call.hass
    entity_ids = _get_entity_ids_from_call(call)
    if not entity_ids:
        _LOGGER.warning("daynight_lighting.turn_on: no entity_id or target.entity_id provided")
        return
    passthrough = {k: v for k, v in call.data.items() if k not in _SERVICE_STRIP_KEYS}

    for eid in entity_ids:
        config_entry, lights = _get_config_and_lights_for_entity_id(hass, eid)
        if not config_entry or not lights:
            _LOGGER.warning(
                "daynight_lighting.turn_on: %s is not a DayNight Lighting main switch or not loaded",
                eid,
            )
            continue
        main_switch = instance_entity(hass, config_entry.entry_id, KEY_MAIN_SWITCH)
        if main_switch is not None and main_switch.is_wall_buttons_blocked():
            _LOGGER.info(
                "daynight_lighting.turn_on: %s wall buttons blocked, ignoring",
                eid,
            )
            continue
        # hold: when True, a visitor interaction is recorded — the lights stay
        # put until the phase ends. Default False: a system automation only
        # switches the lights and the day/night automation keeps managing them.
        hold = call.data.get("hold", False)
        if _user_passed_brightness_or_color(passthrough):
            # Explicit values are an instruction to us, not an intervention to
            # step aside for, so we record them as ours instead of setting
            # manual control. They hold until the mode recomputes; an
            # automation that wants them to stand announces itself with the
            # scene blocker.
            main_switch = instance_entity(
                hass, config_entry.entry_id, KEY_MAIN_SWITCH
            )
            stays_on = passthrough.get("brightness_pct") != 0
            if main_switch is not None:
                main_switch.prepare_lights_applied_by_service(
                    lights,
                    on=stays_on,
                    brightness_pct=passthrough.get("brightness_pct") if stays_on else None,
                    kelvin=passthrough.get("color_temp_kelvin") if stays_on else None,
                )
            _LOGGER.debug(
                "daynight_lighting.turn_on: instance %s — brightness/color passed, recorded as ours",
                eid,
            )
        else:
            # No brightness/color → add our values (day: LUX+circadian, night: night) so result matches.
            main_switch = instance_entity(
                hass, config_entry.entry_id, KEY_MAIN_SWITCH
            )
            if main_switch is not None:
                our_params = main_switch.get_desired_turn_on_params(force_on=hold)
                passthrough = {**our_params, **passthrough}
                # brightness_pct 0 makes the light report itself off
                stays_on = passthrough.get("brightness_pct") != 0
                main_switch.prepare_lights_applied_by_service(
                    lights,
                    on=stays_on,
                    brightness_pct=passthrough.get("brightness_pct") if stays_on else None,
                    kelvin=passthrough.get("color_temp_kelvin") if stays_on else None,
                )
        # Record the hold and cancel the motion-off timer *before* the lights
        # switch. Otherwise a pending night motion-off timer can fire while
        # light.turn_on awaits, switch the light straight back off, and only
        # then would the hold be recorded — leaving the light off but "held on".
        if main_switch is not None:
            main_switch.record_lights_turned_on_by_service(
                lights, hold=hold
            )
        await hass.services.async_call(
            "light",
            "turn_on",
            {"entity_id": lights, **passthrough},
            blocking=True,
        )
        _LOGGER.info(
            "daynight_lighting.turn_on: instance=%s lights=%s data=%s hold=%s",
            eid, lights, passthrough or "(our values)", hold,
        )


async def async_turn_off(call: ServiceCall) -> None:
    """Turn off lights of the given DayNight Lighting instance(s)."""
    hass = call.hass
    entity_ids = _get_entity_ids_from_call(call)
    if not entity_ids:
        _LOGGER.warning("daynight_lighting.turn_off: no entity_id or target.entity_id provided")
        return

    for eid in entity_ids:
        config_entry, lights = _get_config_and_lights_for_entity_id(hass, eid)
        if not config_entry or not lights:
            _LOGGER.warning(
                "daynight_lighting.turn_off: %s is not a DayNight Lighting main switch or not loaded",
                eid,
            )
            continue
        main_switch = instance_entity(hass, config_entry.entry_id, KEY_MAIN_SWITCH)
        if main_switch is not None and main_switch.is_wall_buttons_blocked():
            _LOGGER.info(
                "daynight_lighting.turn_off: %s wall buttons blocked, ignoring",
                eid,
            )
            continue
        passthrough = {k: v for k, v in call.data.items() if k not in _SERVICE_STRIP_KEYS}
        main_switch = instance_entity(
            hass, config_entry.entry_id, KEY_MAIN_SWITCH
        )
        if main_switch is not None:
            main_switch.prepare_lights_turn_off_by_service(lights)
        # hold: see turn_on. Default False, so a system automation only
        # switches the lights off without holding them.
        hold = call.data.get("hold", False)
        await hass.services.async_call(
            "light",
            "turn_off",
            {"entity_id": lights, **passthrough},
            blocking=True,
        )
        if main_switch is not None:
            main_switch.record_lights_turned_off_by_service(lights, hold=hold)
        _LOGGER.info(
            "daynight_lighting.turn_off: instance=%s lights=%s hold=%s",
            eid, lights, hold,
        )


async def async_adjust_brightness(call: ServiceCall) -> None:
    """Dim or brighten an instance by a step, e.g. from a wall button.

    What a step can mean depends on what the instance is doing at the time,
    so the instance decides; this only resolves the entity and logs.
    """
    hass = call.hass
    entity_ids = _get_entity_ids_from_call(call)
    if not entity_ids:
        _LOGGER.warning(
            "daynight_lighting.adjust_brightness: no entity_id or target.entity_id provided"
        )
        return

    step = int(call.data.get("step", 0))
    if step == 0:
        return

    for eid in entity_ids:
        config_entry, lights = _get_config_and_lights_for_entity_id(hass, eid)
        if not config_entry or not lights:
            _LOGGER.warning(
                "daynight_lighting.adjust_brightness: %s is not a DayNight Lighting main switch or not loaded",
                eid,
            )
            continue

        main_switch = instance_entity(
            hass, config_entry.entry_id, KEY_MAIN_SWITCH
        )
        if main_switch is None:
            continue

        _LOGGER.info(
            "daynight_lighting.adjust_brightness: instance=%s step=%+d — %s",
            eid,
            step,
            main_switch.adjust_brightness(step),
        )


async def async_reset_night_brightness(call: ServiceCall) -> None:
    """Drop a dialled-in night brightness, back to the configured value."""
    hass = call.hass
    entity_ids = _get_entity_ids_from_call(call)
    if not entity_ids:
        _LOGGER.warning(
            "daynight_lighting.reset_night_brightness: no entity_id or target.entity_id provided"
        )
        return

    for eid in entity_ids:
        config_entry, lights = _get_config_and_lights_for_entity_id(hass, eid)
        if not config_entry or not lights:
            _LOGGER.warning(
                "daynight_lighting.reset_night_brightness: %s is not a DayNight Lighting main switch or not loaded",
                eid,
            )
            continue

        dial = instance_entity(
            hass, config_entry.entry_id, KEY_NIGHT_BRIGHTNESS
        )
        if dial is None:
            _LOGGER.error(
                "daynight_lighting.reset_night_brightness: night brightness entity not found for %s",
                eid,
            )
            continue

        dial.reset()
        _LOGGER.info(
            "daynight_lighting.reset_night_brightness: instance=%s back to %d%%",
            eid,
            dial.native_value,
        )


async def async_reset_day_brightness(call: ServiceCall) -> None:
    """Drop a dialled-in day brightness, back to the configured value."""
    hass = call.hass
    entity_ids = _get_entity_ids_from_call(call)
    if not entity_ids:
        _LOGGER.warning(
            "daynight_lighting.reset_day_brightness: no entity_id or target.entity_id provided"
        )
        return

    for eid in entity_ids:
        config_entry, lights = _get_config_and_lights_for_entity_id(hass, eid)
        if not config_entry or not lights:
            _LOGGER.warning(
                "daynight_lighting.reset_day_brightness: %s is not a DayNight Lighting main switch or not loaded",
                eid,
            )
            continue

        dial = instance_entity(
            hass, config_entry.entry_id, KEY_DAY_BRIGHTNESS
        )
        if dial is None:
            _LOGGER.error(
                "daynight_lighting.reset_day_brightness: day brightness entity not found for %s",
                eid,
            )
            continue

        dial.reset()
        _LOGGER.info("daynight_lighting.reset_day_brightness: instance=%s back to %d%%", eid, dial.native_value)


async def async_hold_all(call: ServiceCall) -> None:
    """Hold every light of the given instance(s) until the phase ends.

    The bulk replacement for the removed "Manual control" switch: a single
    call that stops the automation from touching any light of the instance.
    """
    hass = call.hass
    entity_ids = _get_entity_ids_from_call(call)
    if not entity_ids:
        _LOGGER.warning(
            "daynight_lighting.hold_all: no entity_id or target.entity_id provided"
        )
        return

    for eid in entity_ids:
        config_entry, lights = _get_config_and_lights_for_entity_id(hass, eid)
        if not config_entry or not lights:
            _LOGGER.warning(
                "daynight_lighting.hold_all: %s is not a DayNight Lighting main switch or not loaded",
                eid,
            )
            continue

        main_switch = instance_entity(
            hass, config_entry.entry_id, KEY_MAIN_SWITCH
        )
        if main_switch is None:
            _LOGGER.error(
                "daynight_lighting.hold_all: main_switch not found for %s",
                eid,
            )
            continue

        main_switch.hold_all_lights()
        _LOGGER.info("daynight_lighting.hold_all: instance=%s lights held", eid)


async def async_release_hold(call: ServiceCall) -> None:
    """Drop the holds of the given instance(s) and restore the configured state.

    A ``turn_on``/``turn_off`` holds the lights in place until the phase
    changes. This service releases that hold early, resets the brightness
    dials to their configured starting points and re-applies the mode.
    """
    hass = call.hass
    entity_ids = _get_entity_ids_from_call(call)
    if not entity_ids:
        _LOGGER.warning(
            "daynight_lighting.release_hold: no entity_id or target.entity_id provided"
        )
        return

    for eid in entity_ids:
        config_entry, lights = _get_config_and_lights_for_entity_id(hass, eid)
        if not config_entry or not lights:
            _LOGGER.warning(
                "daynight_lighting.release_hold: %s is not a DayNight Lighting main switch or not loaded",
                eid,
            )
            continue

        main_switch = instance_entity(
            hass, config_entry.entry_id, KEY_MAIN_SWITCH
        )
        if main_switch is None:
            _LOGGER.error(
                "daynight_lighting.release_hold: main_switch not found for %s",
                eid,
            )
            continue

        main_switch.release_hold()
        _LOGGER.info("daynight_lighting.release_hold: instance=%s holds released", eid)


async def async_calibrate_lux(call: ServiceCall) -> None:
    """Calibrate LUX sensor to compensate for lamp contribution.

    This service measures the LUX contribution of the configured lights at
    100% brightness by:
    1. Turning all lights to 100% and measuring LUX after 30 seconds.
    2. Turning all lights off and measuring LUX after 30 seconds.
    3. Computing the difference and storing it as calibration data.

    This should be run **after sunset** in a dark room (no external light)
    for accurate results.
    """
    hass = call.hass
    entity_ids = _get_entity_ids_from_call(call)
    if not entity_ids:
        _LOGGER.warning("daynight_lighting.calibrate_lux: no entity_id provided")
        return

    for eid in entity_ids:
        config_entry, lights = _get_config_and_lights_for_entity_id(hass, eid)
        if not config_entry or not lights:
            _LOGGER.warning(
                "daynight_lighting.calibrate_lux: %s is not a DayNight Lighting main switch or not loaded",
                eid,
            )
            continue

        main_switch = instance_entity(
            hass, config_entry.entry_id, KEY_MAIN_SWITCH
        )
        if main_switch is None:
            _LOGGER.error(
                "daynight_lighting.calibrate_lux: main_switch not found for %s",
                eid,
            )
            continue

        # Get the light sensor entity
        illuminance_reader = main_switch._illuminance
        light_sensor = illuminance_reader.get_light_sensor_entity()
        if not light_sensor:
            _LOGGER.error(
                "daynight_lighting.calibrate_lux: instance %s has no light_sensor configured",
                eid,
            )
            continue

        _LOGGER.info(
            "daynight_lighting.calibrate_lux: starting calibration for instance %s",
            eid,
        )

        # Step 1: Turn lights to 100% and wait
        _LOGGER.info(
            "daynight_lighting.calibrate_lux: turning lights to 100%% brightness..."
        )
        main_switch.prepare_lights_applied_by_service(
            lights, on=True, brightness_pct=100
        )
        await hass.services.async_call(
            "light",
            "turn_on",
            {"entity_id": lights, "brightness_pct": 100},
            blocking=True,
        )
        await asyncio.sleep(30)

        lux_at_100 = illuminance_reader.get_lux_raw()
        if lux_at_100 is None:
            _LOGGER.error(
                "daynight_lighting.calibrate_lux: failed to read LUX at 100%% (sensor unavailable)"
            )
            continue

        _LOGGER.info(
            "daynight_lighting.calibrate_lux: LUX at 100%% = %.1f", lux_at_100
        )

        # Step 2: Turn lights off and wait
        _LOGGER.info("daynight_lighting.calibrate_lux: turning lights off...")
        main_switch.prepare_lights_applied_by_service(lights, on=False)
        await hass.services.async_call(
            "light",
            "turn_off",
            {"entity_id": lights},
            blocking=True,
        )
        await asyncio.sleep(30)

        lux_at_0 = illuminance_reader.get_lux_raw()
        if lux_at_0 is None:
            _LOGGER.error(
                "daynight_lighting.calibrate_lux: failed to read LUX at 0%% (sensor unavailable)"
            )
            continue

        _LOGGER.info("daynight_lighting.calibrate_lux: LUX at 0%% = %.1f", lux_at_0)

        # Step 3: Compute difference and store
        lux_contribution = max(0.0, lux_at_100 - lux_at_0)
        _LOGGER.info(
            "daynight_lighting.calibrate_lux: lamp contribution = %.1f lux",
            lux_contribution,
        )

        # Store in persistent state
        state_ctrl = main_switch._state_ctrl
        state_ctrl.set_lux_calibration(lux_contribution)

        # Update illuminance reader
        illuminance_reader.set_lux_calibration(lux_contribution)

        _LOGGER.info(
            "daynight_lighting.calibrate_lux: calibration complete for instance %s"
            " (lamp contribution: %.1f lux)",
            eid,
            lux_contribution,
        )


async def async_start_sleep_mode(call: ServiceCall) -> None:
    """Immediately start Sleep Mode regardless of schedule.

    This service bypasses schedule checking and starts sleep mode now.
    Sleep Mode 2.0 uses existing state infrastructure for gradual dimming.
    """
    hass = call.hass
    entity_ids = _get_entity_ids_from_call(call)
    if not entity_ids:
        _LOGGER.warning("daynight_lighting.start_sleep_mode: no entity_id or target.entity_id provided")
        return

    # Extract optional parameters
    duration_min = call.data.get("duration_min")
    brightness_pct = call.data.get("brightness_pct")
    color_temp_kelvin = call.data.get("color_temp_kelvin")

    for eid in entity_ids:
        config_entry, lights = _get_config_and_lights_for_entity_id(hass, eid)
        if not config_entry or not lights:
            _LOGGER.warning(
                "daynight_lighting.start_sleep_mode: %s is not a DayNight Lighting main switch or not loaded",
                eid,
            )
            continue

        main_switch = instance_entity(
            hass, config_entry.entry_id, KEY_MAIN_SWITCH
        )
        if main_switch is None:
            _LOGGER.error(
                "daynight_lighting.start_sleep_mode: main_switch not found for %s",
                eid,
            )
            continue

        # Trigger immediate sleep mode with optional overrides
        main_switch.start_sleep_mode_now(
            duration_min=duration_min,
            brightness_pct=brightness_pct,
            color_temp_kelvin=color_temp_kelvin,
        )
        _LOGGER.info(
            "Started Sleep Mode for instance %s (duration=%s, brightness=%s, kelvin=%s)",
            eid,
            duration_min if duration_min is not None else "config",
            brightness_pct if brightness_pct is not None else "config",
            color_temp_kelvin if color_temp_kelvin is not None else "config",
        )


async def async_start_wakeup_mode(call: ServiceCall) -> None:
    """Immediately start Wake-up Mode regardless of schedule.

    This service bypasses schedule checking and starts wake-up mode now.
    Wake-up Mode uses actual start time for deterministic progress calculation.
    """
    hass = call.hass
    entity_ids = _get_entity_ids_from_call(call)
    if not entity_ids:
        _LOGGER.warning("daynight_lighting.start_wakeup_mode: no entity_id or target.entity_id provided")
        return

    # Extract optional parameters
    duration_min = call.data.get("duration_min")
    start_brightness_pct = call.data.get("start_brightness_pct")
    end_brightness_pct = call.data.get("end_brightness_pct")
    color_temp_kelvin = call.data.get("color_temp_kelvin")

    for eid in entity_ids:
        config_entry, lights = _get_config_and_lights_for_entity_id(hass, eid)
        if not config_entry or not lights:
            _LOGGER.warning(
                "daynight_lighting.start_wakeup_mode: %s is not a DayNight Lighting main switch or not loaded",
                eid,
            )
            continue

        main_switch = instance_entity(
            hass, config_entry.entry_id, KEY_MAIN_SWITCH
        )
        if main_switch is None:
            _LOGGER.error(
                "daynight_lighting.start_wakeup_mode: main_switch not found for %s",
                eid,
            )
            continue

        # Trigger immediate wake-up mode with optional overrides
        main_switch.start_wakeup_mode_now(
            duration_min=duration_min,
            start_brightness_pct=start_brightness_pct,
            end_brightness_pct=end_brightness_pct,
            color_temp_kelvin=color_temp_kelvin,
        )
        _LOGGER.info(
            "Started Wake-up Mode for instance %s (duration=%s, start=%s, end=%s, kelvin=%s)",
            eid,
            duration_min if duration_min is not None else "config",
            start_brightness_pct if start_brightness_pct is not None else "config",
            end_brightness_pct if end_brightness_pct is not None else "auto",
            color_temp_kelvin if color_temp_kelvin is not None else "config",
        )


async def async_stop_sleep_mode(call: ServiceCall) -> None:
    """Immediately stop Sleep Mode and return to normal day/night mode.

    This service exits sleep mode and clears the sleep block, returning
    control to the schedule (day or night mode based on current time).
    """
    hass = call.hass
    entity_ids = _get_entity_ids_from_call(call)
    if not entity_ids:
        _LOGGER.warning("daynight_lighting.stop_sleep_mode: no entity_id or target.entity_id provided")
        return

    for eid in entity_ids:
        config_entry, lights = _get_config_and_lights_for_entity_id(hass, eid)
        if not config_entry or not lights:
            _LOGGER.warning(
                "daynight_lighting.stop_sleep_mode: %s is not a DayNight Lighting main switch or not loaded",
                eid,
            )
            continue

        main_switch = instance_entity(
            hass, config_entry.entry_id, KEY_MAIN_SWITCH
        )
        if main_switch is None:
            _LOGGER.error(
                "daynight_lighting.stop_sleep_mode: main_switch not found for %s",
                eid,
            )
            continue

        # Stop sleep mode and return to normal schedule
        main_switch.stop_sleep_mode_now()
        _LOGGER.info(
            "Stopped Sleep Mode for instance %s",
            eid,
        )


async def async_stop_wakeup_mode(call: ServiceCall) -> None:
    """Immediately stop Wake-up Mode and return to normal day/night mode.

    This service exits wake-up mode, returning control to the schedule
    (day or night mode based on current time).
    """
    hass = call.hass
    entity_ids = _get_entity_ids_from_call(call)
    if not entity_ids:
        _LOGGER.warning("daynight_lighting.stop_wakeup_mode: no entity_id or target.entity_id provided")
        return

    for eid in entity_ids:
        config_entry, lights = _get_config_and_lights_for_entity_id(hass, eid)
        if not config_entry or not lights:
            _LOGGER.warning(
                "daynight_lighting.stop_wakeup_mode: %s is not a DayNight Lighting main switch or not loaded",
                eid,
            )
            continue

        main_switch = instance_entity(
            hass, config_entry.entry_id, KEY_MAIN_SWITCH
        )
        if main_switch is None:
            _LOGGER.error(
                "daynight_lighting.stop_wakeup_mode: main_switch not found for %s",
                eid,
            )
            continue

        # Stop wake-up mode and return to normal schedule
        main_switch.stop_wakeup_mode_now()
        _LOGGER.info(
            "Stopped Wake-up Mode for instance %s",
            eid,
        )
