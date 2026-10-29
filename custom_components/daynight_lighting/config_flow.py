"""Config flow for DayNight Lighting integration."""

from __future__ import annotations

import logging
import re
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers.selector import (
    AreaSelector,
    AreaSelectorConfig,
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
)

try:
    from homeassistant.helpers.selector import SelectSelector, SelectSelectorConfig, TimeSelector
    _HAS_TIME_SELECTOR = True
    _HAS_SELECT_SELECTOR = True
except ImportError:
    _HAS_TIME_SELECTOR = False
    _HAS_SELECT_SELECTOR = False

try:
    from homeassistant.data_entry_flow import section
    _HAS_SECTIONS = True
except ImportError:
    _HAS_SECTIONS = False

from .const import (
    CONF_AREA_ID,
    CONF_BRIGHTNESS_CHANGE_THRESHOLD_PCT,
    CONF_CIRCADIAN_ENABLED,
    CONF_CIRCADIAN_MAX_KELVIN,
    CONF_CIRCADIAN_MIN_KELVIN,
    CONF_DAY_FIXED_BRIGHTNESS_PCT,
    CONF_DAY_MAX_BRIGHTNESS,
    CONF_DAY_MIN_BRIGHTNESS,
    CONF_DAY_MODE_FALLBACK,
    CONF_EXCLUDED_MOTION_SENSORS,
    CONF_FLAPPING_FREEZE_MIN,
    CONF_INCLUDED_LIGHTS,
    CONF_INITIAL_TRANSITION_SECONDS,
    CONF_INSTANCE_NAME,
    CONF_LIGHT_SENSOR,
    CONF_LUX_SMOOTHING_SAMPLES,
    CONF_MODE_TRANSITION_SECONDS,
    CONF_NIGHT_MODE_FALLBACK,
    CONF_SLEEP_ENABLED,
    CONF_SLEEP_START_TIME,
    CONF_SLEEP_DURATION_MIN,
    CONF_SLEEP_TARGET_BRIGHTNESS,
    CONF_SLEEP_TARGET_KELVIN,
    CONF_SLEEP_USE_AUTO_VALUES,
    CONF_LIGHTS,
    CONF_LUX_OFF,
    CONF_LUX_ON,
    CONF_MOTION_OFF_DELAY_MIN,
    CONF_MOTION_SENSOR,
    CONF_NIGHT_BRIGHTNESS,
    CONF_NIGHT_MODE_START,
    CONF_NIGHT_MODE_START_TIME,
    CONF_ON_ENTER_NIGHT,
    CONF_TRANSITION_SECONDS,
    CONF_USE_AREA_DISCOVERY,
    CONF_WAKEUP_ENABLED,
    CONF_WAKEUP_TIME,
    CONF_WAKEUP_DURATION_MIN,
    CONF_WAKEUP_END_KELVIN,
    CONF_WAKEUP_START_BRIGHTNESS,
    CONF_WAKEUP_USE_AUTO_VALUES,
    CONF_WEATHER_ENABLED,
    CONF_WEATHER_ENTITY,
    DAY_FALLBACK_CIRCADIAN_ONLY,
    DAY_FALLBACK_FIXED,
    DAY_FALLBACK_OFF,
    DAY_FALLBACK_SKIP,
    DEFAULT_BRIGHTNESS_CHANGE_THRESHOLD_PCT,
    DEFAULT_CIRCADIAN_ENABLED,
    DEFAULT_CIRCADIAN_MAX_KELVIN,
    DEFAULT_CIRCADIAN_MIN_KELVIN,
    DEFAULT_DAY_FIXED_BRIGHTNESS_PCT,
    DEFAULT_DAY_MAX_BRIGHTNESS,
    DEFAULT_DAY_MIN_BRIGHTNESS,
    DEFAULT_DAY_MODE_FALLBACK,
    DEFAULT_FLAPPING_FREEZE_MIN,
    DEFAULT_INITIAL_TRANSITION_SECONDS,
    DEFAULT_INSTANCE_NAME,
    DEFAULT_LUX_SMOOTHING_SAMPLES,
    MAX_TICK_TRANSITION_SECONDS,
    DEFAULT_LUX_OFF,
    DEFAULT_LUX_ON,
    DEFAULT_MODE_TRANSITION_SECONDS,
    DEFAULT_NIGHT_MODE_FALLBACK,
    DEFAULT_SLEEP_ENABLED,
    DEFAULT_SLEEP_START_TIME_STR,
    DEFAULT_SLEEP_DURATION_MIN,
    DEFAULT_SLEEP_TARGET_BRIGHTNESS,
    DEFAULT_SLEEP_TARGET_KELVIN,
    DEFAULT_SLEEP_USE_AUTO_VALUES,
    DEFAULT_MOTION_OFF_DELAY_MIN,
    DEFAULT_NIGHT_BRIGHTNESS,
    DEFAULT_NIGHT_MODE_START,
    DEFAULT_NIGHT_MODE_START_TIME_STR,
    DEFAULT_ON_ENTER_NIGHT,
    DEFAULT_TRANSITION_SECONDS,
    DEFAULT_WAKEUP_ENABLED,
    DEFAULT_WAKEUP_TIME_STR,
    DEFAULT_WAKEUP_DURATION_MIN,
    DEFAULT_WAKEUP_END_KELVIN,
    DEFAULT_WAKEUP_START_BRIGHTNESS,
    DEFAULT_WAKEUP_USE_AUTO_VALUES,
    DEFAULT_WEATHER_ENABLED,
    DOMAIN,
    NIGHT_FALLBACK_KEEP,
    NIGHT_FALLBACK_OFF,
    NIGHT_FALLBACK_ON,
    NIGHT_FALLBACK_SKIP,
)

_LOGGER = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
#  Section keys (only used for UI grouping, not stored in options)
# ---------------------------------------------------------------------------

SECTION_AREA = "area_discovery"
SECTION_DEVICES = "devices_sensors"
SECTION_DAY = "day_mode"
SECTION_NIGHT = "night_mode"
SECTION_CIRCADIAN = "circadian"
SECTION_TRANSITIONS = "transitions"
SECTION_SLEEP = "sleep_mode"
SECTION_WAKEUP = "wakeup_mode"
SECTION_WEATHER = "weather_brightness"


def _flatten_sections(user_input: dict[str, Any]) -> dict[str, Any]:
    """Flatten section-grouped user input into a flat dict.

    HA delivers section fields as nested dicts::

        {"devices_sensors": {"lights": [...], ...}, "day_mode": {...}}

    We flatten this to the original flat structure so the saved options
    format does not change::

        {"lights": [...], "lux_on": 10.0, ...}

    Non-dict values (if any top-level fields exist) are kept as-is.
    """
    result: dict[str, Any] = {}
    for key, value in user_input.items():
        if isinstance(value, dict):
            result.update(value)
        else:
            result[key] = value
    return result


class DayNightLightingConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for DayNight Lighting."""

    VERSION = 1

    async def async_step_user(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Handle the initial step: optional area and instance name (used for entity_id like daynight_lighting_{room})."""
        errors: dict[str, str] = {}

        if user_input is not None:
            area_id = user_input.get(CONF_AREA_ID)
            name_from_user = (user_input.get(CONF_INSTANCE_NAME) or "").strip()
            if area_id and not name_from_user:
                area_reg = ar.async_get(self.hass)
                area = area_reg.async_get(area_id)
                name = area.name if area else DEFAULT_INSTANCE_NAME
            else:
                name = name_from_user or DEFAULT_INSTANCE_NAME
            slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") or "default"
            await self.async_set_unique_id(slug)
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title=name,
                data={
                    CONF_INSTANCE_NAME: name,
                    CONF_AREA_ID: area_id or None,
                },
            )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Optional(CONF_AREA_ID, default=None): AreaSelector(
                        AreaSelectorConfig()
                    ),
                    vol.Optional(CONF_INSTANCE_NAME, default=""): str,
                },
            ),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> OptionsFlowHandler:
        """Get the options flow for this handler."""
        return OptionsFlowHandler()


class OptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options flow for DayNight Lighting."""

    async def async_step_init(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Handle options: lights, sensors, area, and day/night parameters."""
        errors: dict[str, str] = {}
        opts = self.config_entry.options

        if user_input is not None:
            # Get instance_name early for logging
            instance_name = (
                self.config_entry.data.get(CONF_INSTANCE_NAME)
                or opts.get(CONF_INSTANCE_NAME)
                or DEFAULT_INSTANCE_NAME
            )
            _LOGGER.debug("[%s] Options flow received user_input: %s", instance_name, user_input)
            _LOGGER.debug("[%s] Current options: %s", instance_name, opts)

            # If the devices section was submitted, check which sensor fields
            # should be removed BEFORE flattening (defaults are applied during flattening)
            sensors_to_remove = []
            if SECTION_DEVICES in user_input:
                devices_section = user_input.get(SECTION_DEVICES, {})
                _LOGGER.debug("[%s] Devices section content: %s", instance_name, devices_section)
                for sensor_key in (CONF_LIGHT_SENSOR, CONF_MOTION_SENSOR):
                    # If the sensor field is missing, explicitly None, or an
                    # empty list (cleared multi-select), mark it for removal.
                    value = devices_section.get(sensor_key) if sensor_key in devices_section else None
                    if value is None or value == []:
                        sensors_to_remove.append(sensor_key)
                        _LOGGER.debug("[%s] Marking %s for removal", instance_name, sensor_key)

            # Flatten sections → flat dict (same format as before sections)
            flat_input = _flatten_sections(user_input)

            # Remove sensors that were cleared by the user
            for sensor_key in sensors_to_remove:
                flat_input[sensor_key] = None

            # Preserve instance_name and area_id; merge with existing
            area_id = opts.get(CONF_AREA_ID) or self.config_entry.data.get(CONF_AREA_ID)
            options = {
                **opts,
                CONF_INSTANCE_NAME: instance_name,
                CONF_AREA_ID: area_id,
                **flat_input,
            }
            # When area discovery is off, the explicit lights live in ``lights``.
            # If the user just disabled discovery but their selection is still in
            # the area section's ``included_lights``, carry it over and drop the
            # now-unused area selection, so the lights show in exactly one place
            # ("Additional lights") instead of appearing twice.
            use_area_discovery = bool(options.get(CONF_USE_AREA_DISCOVERY, False))
            if (
                not use_area_discovery
                and not options.get(CONF_LIGHTS)
                and options.get(CONF_INCLUDED_LIGHTS)
            ):
                options[CONF_LIGHTS] = list(options[CONF_INCLUDED_LIGHTS])
                options[CONF_INCLUDED_LIGHTS] = []
            _LOGGER.debug("[%s] Saving options: %s", instance_name, options)
            _LOGGER.debug("[%s] Sensor values - light: %s, motion: %s", instance_name, options.get(CONF_LIGHT_SENSOR), options.get(CONF_MOTION_SENSOR))
            return self.async_create_entry(title="", data=options)

        def _f(key: str, default: float | int | str) -> float | int | str:
            return opts.get(key, default)

        # Helper to create description with suggested_value for sensors
        def _sensor_description(key: str) -> dict[str, Any]:
            val = opts.get(key)
            if val is None:
                return {}
            # Multi-select selectors need a list as suggested value; a legacy
            # single-string option is wrapped so the form still pre-fills it.
            if isinstance(val, str):
                val = [val]
            return {"suggested_value": val}

        # --- Build sub-schemas for each section ---

        # Check if area is configured
        area_id = opts.get(CONF_AREA_ID) or self.config_entry.data.get(CONF_AREA_ID)
        has_area = area_id is not None

        # Area discovery schema (only shown when area is configured)
        area_discovery_schema_fields: dict[Any, Any] = {}
        if has_area:
            # Use area discovery toggle
            area_discovery_schema_fields[vol.Optional(
                CONF_USE_AREA_DISCOVERY,
                default=_f(CONF_USE_AREA_DISCOVERY, True),
            )] = bool

            # Included lights selector (applies when area discovery is enabled)
            # Always include this field to avoid dynamic schema issues
            area_discovery_schema_fields[vol.Optional(
                CONF_INCLUDED_LIGHTS,
                default=_f(CONF_INCLUDED_LIGHTS, []),
            )] = EntitySelector(
                EntitySelectorConfig(domain="light", multiple=True)
            )

            # Motion sensors to ignore during area discovery (e.g. a camera
            # AI-detection sensor that latches on). Only the discovered set is
            # filtered; a manually configured motion sensor is still honoured.
            area_discovery_schema_fields[vol.Optional(
                CONF_EXCLUDED_MOTION_SENSORS,
                default=_f(CONF_EXCLUDED_MOTION_SENSORS, []),
            )] = EntitySelector(
                EntitySelectorConfig(domain="binary_sensor", multiple=True)
            )

        # Build devices schema - always show manual selectors
        # Even with area discovery enabled, users may want to add manual sensors
        # or remove previously configured ones
        devices_schema = vol.Schema(
            {
                vol.Optional(
                    CONF_LIGHTS,
                    default=_f(CONF_LIGHTS, []),
                ): EntitySelector(
                    EntitySelectorConfig(domain="light", multiple=True),
                ),
                vol.Optional(
                    CONF_LIGHT_SENSOR,
                    description=_sensor_description(CONF_LIGHT_SENSOR),
                ): EntitySelector(
                    EntitySelectorConfig(domain=["sensor", "group"], multiple=True),
                ),
                vol.Optional(
                    CONF_MOTION_SENSOR,
                    description=_sensor_description(CONF_MOTION_SENSOR),
                ): EntitySelector(
                    EntitySelectorConfig(domain=["binary_sensor", "group"], multiple=True),
                ),
            }
        )

        day_schema = vol.Schema(
            {
                vol.Optional(
                    CONF_LUX_ON,
                    default=_f(CONF_LUX_ON, DEFAULT_LUX_ON),
                ): NumberSelector(NumberSelectorConfig(min=0, max=500, step=0.1)),
                vol.Optional(
                    CONF_LUX_OFF,
                    default=_f(CONF_LUX_OFF, DEFAULT_LUX_OFF),
                ): NumberSelector(NumberSelectorConfig(min=0, max=1000, step=1)),
                vol.Optional(
                    CONF_DAY_MIN_BRIGHTNESS,
                    default=_f(CONF_DAY_MIN_BRIGHTNESS, DEFAULT_DAY_MIN_BRIGHTNESS),
                ): NumberSelector(NumberSelectorConfig(min=0, max=100, step=1)),
                vol.Optional(
                    CONF_DAY_MAX_BRIGHTNESS,
                    default=_f(CONF_DAY_MAX_BRIGHTNESS, DEFAULT_DAY_MAX_BRIGHTNESS),
                ): NumberSelector(NumberSelectorConfig(min=0, max=100, step=1)),
                vol.Optional(
                    CONF_LUX_SMOOTHING_SAMPLES,
                    default=_f(CONF_LUX_SMOOTHING_SAMPLES, DEFAULT_LUX_SMOOTHING_SAMPLES),
                ): NumberSelector(NumberSelectorConfig(min=1, max=10, step=1)),
                vol.Optional(
                    CONF_BRIGHTNESS_CHANGE_THRESHOLD_PCT,
                    default=_f(CONF_BRIGHTNESS_CHANGE_THRESHOLD_PCT, DEFAULT_BRIGHTNESS_CHANGE_THRESHOLD_PCT),
                ): NumberSelector(NumberSelectorConfig(min=0, max=20, step=1)),
                vol.Optional(
                    CONF_FLAPPING_FREEZE_MIN,
                    default=_f(CONF_FLAPPING_FREEZE_MIN, DEFAULT_FLAPPING_FREEZE_MIN),
                ): NumberSelector(NumberSelectorConfig(min=1, max=30, step=1)),
                vol.Optional(
                    CONF_DAY_MODE_FALLBACK,
                    default=_f(CONF_DAY_MODE_FALLBACK, DEFAULT_DAY_MODE_FALLBACK),
                ): (
                    SelectSelector(
                        SelectSelectorConfig(
                            options=[
                                {"value": DAY_FALLBACK_SKIP, "label": "Skip (do nothing)"},
                                {"value": DAY_FALLBACK_FIXED, "label": "Fixed brightness"},
                                {"value": DAY_FALLBACK_CIRCADIAN_ONLY, "label": "Circadian color only"},
                                {"value": DAY_FALLBACK_OFF, "label": "Turn lights off"},
                            ],
                            translation_key="day_mode_fallback",
                        ),
                    )
                    if _HAS_SELECT_SELECTOR
                    else vol.In((DAY_FALLBACK_SKIP, DAY_FALLBACK_FIXED, DAY_FALLBACK_CIRCADIAN_ONLY, DAY_FALLBACK_OFF))
                ),
                vol.Optional(
                    CONF_DAY_FIXED_BRIGHTNESS_PCT,
                    default=_f(CONF_DAY_FIXED_BRIGHTNESS_PCT, DEFAULT_DAY_FIXED_BRIGHTNESS_PCT),
                ): NumberSelector(NumberSelectorConfig(min=0, max=100, step=1)),
            }
        )

        night_schema = vol.Schema(
            {
                vol.Optional(
                    CONF_NIGHT_MODE_START_TIME,
                    default=_f(CONF_NIGHT_MODE_START_TIME, DEFAULT_NIGHT_MODE_START_TIME_STR),
                ): TimeSelector() if _HAS_TIME_SELECTOR else str,
                vol.Optional(
                    CONF_NIGHT_MODE_START,
                    default=_f(CONF_NIGHT_MODE_START, DEFAULT_NIGHT_MODE_START),
                ): (
                    SelectSelector(
                        SelectSelectorConfig(
                            options=[
                                {"value": "sun_below_horizon", "label": "At sunset (sun below horizon)"},
                                {"value": "at_time", "label": "At configured time only"},
                            ],
                            translation_key="night_mode_start",
                        ),
                    )
                    if _HAS_SELECT_SELECTOR
                    else vol.In(("sun_below_horizon", "at_time"))
                ),
                vol.Optional(
                    CONF_MOTION_OFF_DELAY_MIN,
                    default=_f(CONF_MOTION_OFF_DELAY_MIN, DEFAULT_MOTION_OFF_DELAY_MIN),
                ): NumberSelector(NumberSelectorConfig(min=1, max=120, step=1)),
                vol.Optional(
                    CONF_NIGHT_BRIGHTNESS,
                    default=_f(CONF_NIGHT_BRIGHTNESS, DEFAULT_NIGHT_BRIGHTNESS),
                ): NumberSelector(NumberSelectorConfig(min=0, max=100, step=1)),
                vol.Optional(
                    CONF_ON_ENTER_NIGHT,
                    default=_f(CONF_ON_ENTER_NIGHT, DEFAULT_ON_ENTER_NIGHT),
                ): (
                    SelectSelector(
                        SelectSelectorConfig(
                            options=[
                                {"value": "leave", "label": "Leave lights as they are"},
                                {"value": "turn_off", "label": "Turn lights off"},
                            ],
                            translation_key="on_enter_night",
                        ),
                    )
                    if _HAS_SELECT_SELECTOR
                    else vol.In(("leave", "turn_off"))
                ),
                vol.Optional(
                    CONF_NIGHT_MODE_FALLBACK,
                    default=_f(CONF_NIGHT_MODE_FALLBACK, DEFAULT_NIGHT_MODE_FALLBACK),
                ): (
                    SelectSelector(
                        SelectSelectorConfig(
                            options=[
                                {"value": NIGHT_FALLBACK_SKIP, "label": "Skip (do nothing)"},
                                {"value": NIGHT_FALLBACK_ON, "label": "Turn lights on"},
                                {"value": NIGHT_FALLBACK_KEEP, "label": "Keep current state"},
                                {"value": NIGHT_FALLBACK_OFF, "label": "Turn lights off"},
                            ],
                            translation_key="night_mode_fallback",
                        ),
                    )
                    if _HAS_SELECT_SELECTOR
                    else vol.In((NIGHT_FALLBACK_SKIP, NIGHT_FALLBACK_ON, NIGHT_FALLBACK_KEEP, NIGHT_FALLBACK_OFF))
                ),
            }
        )

        circadian_schema = vol.Schema(
            {
                vol.Optional(
                    CONF_CIRCADIAN_ENABLED,
                    default=_f(CONF_CIRCADIAN_ENABLED, DEFAULT_CIRCADIAN_ENABLED),
                ): bool,
                vol.Optional(
                    CONF_CIRCADIAN_MIN_KELVIN,
                    default=_f(CONF_CIRCADIAN_MIN_KELVIN, DEFAULT_CIRCADIAN_MIN_KELVIN),
                ): NumberSelector(NumberSelectorConfig(min=2000, max=6500, step=100)),
                vol.Optional(
                    CONF_CIRCADIAN_MAX_KELVIN,
                    default=_f(CONF_CIRCADIAN_MAX_KELVIN, DEFAULT_CIRCADIAN_MAX_KELVIN),
                ): NumberSelector(NumberSelectorConfig(min=2000, max=6500, step=100)),
            }
        )

        transitions_schema = vol.Schema(
            {
                vol.Optional(
                    CONF_TRANSITION_SECONDS,
                    default=_f(CONF_TRANSITION_SECONDS, DEFAULT_TRANSITION_SECONDS),
                ): NumberSelector(
                    NumberSelectorConfig(min=0, max=MAX_TICK_TRANSITION_SECONDS, step=1),
                ),
                vol.Optional(
                    CONF_INITIAL_TRANSITION_SECONDS,
                    default=_f(CONF_INITIAL_TRANSITION_SECONDS, DEFAULT_INITIAL_TRANSITION_SECONDS),
                ): NumberSelector(NumberSelectorConfig(min=0, max=120, step=1)),
                vol.Optional(
                    CONF_MODE_TRANSITION_SECONDS,
                    default=_f(CONF_MODE_TRANSITION_SECONDS, DEFAULT_MODE_TRANSITION_SECONDS),
                ): NumberSelector(NumberSelectorConfig(min=0, max=300, step=1)),
            }
        )

        # Sleep mode: use_auto_values determines if we show custom inputs
        sleep_use_auto = bool(opts.get(CONF_SLEEP_USE_AUTO_VALUES, DEFAULT_SLEEP_USE_AUTO_VALUES))

        sleep_schema_fields: dict[Any, Any] = {
            vol.Optional(
                CONF_SLEEP_ENABLED,
                default=_f(CONF_SLEEP_ENABLED, DEFAULT_SLEEP_ENABLED),
            ): bool,
            vol.Optional(
                CONF_SLEEP_START_TIME,
                default=_f(CONF_SLEEP_START_TIME, DEFAULT_SLEEP_START_TIME_STR),
            ): TimeSelector() if _HAS_TIME_SELECTOR else str,
            vol.Optional(
                CONF_SLEEP_DURATION_MIN,
                default=_f(CONF_SLEEP_DURATION_MIN, DEFAULT_SLEEP_DURATION_MIN),
            ): NumberSelector(
                NumberSelectorConfig(
                    min=15,
                    max=240,
                    step=5,
                    mode="slider",
                    unit_of_measurement="minutes",
                )
            ),
            vol.Optional(
                CONF_SLEEP_USE_AUTO_VALUES,
                default=_f(CONF_SLEEP_USE_AUTO_VALUES, DEFAULT_SLEEP_USE_AUTO_VALUES),
            ): bool,
        }

        # Only show custom inputs when auto-values is disabled
        if not sleep_use_auto:
            sleep_schema_fields[
                vol.Optional(
                    CONF_SLEEP_TARGET_BRIGHTNESS,
                    default=_f(CONF_SLEEP_TARGET_BRIGHTNESS, DEFAULT_SLEEP_TARGET_BRIGHTNESS),
                )
            ] = NumberSelector(NumberSelectorConfig(min=0, max=100, step=1))
            sleep_schema_fields[
                vol.Optional(
                    CONF_SLEEP_TARGET_KELVIN,
                    default=_f(CONF_SLEEP_TARGET_KELVIN, DEFAULT_SLEEP_TARGET_KELVIN),
                )
            ] = NumberSelector(NumberSelectorConfig(min=2000, max=4000, step=100))

        sleep_schema = vol.Schema(sleep_schema_fields)

        # Wake-up mode: use_auto_values determines if we show custom inputs
        wakeup_use_auto = bool(opts.get(CONF_WAKEUP_USE_AUTO_VALUES, DEFAULT_WAKEUP_USE_AUTO_VALUES))

        wakeup_schema_fields: dict[Any, Any] = {
            vol.Optional(
                CONF_WAKEUP_ENABLED,
                default=_f(CONF_WAKEUP_ENABLED, DEFAULT_WAKEUP_ENABLED),
            ): bool,
            vol.Optional(
                CONF_WAKEUP_TIME,
                default=_f(CONF_WAKEUP_TIME, DEFAULT_WAKEUP_TIME_STR),
            ): TimeSelector() if _HAS_TIME_SELECTOR else str,
            vol.Optional(
                CONF_WAKEUP_DURATION_MIN,
                default=_f(CONF_WAKEUP_DURATION_MIN, DEFAULT_WAKEUP_DURATION_MIN),
            ): NumberSelector(NumberSelectorConfig(min=5, max=120, step=5)),
            vol.Optional(
                CONF_WAKEUP_USE_AUTO_VALUES,
                default=_f(CONF_WAKEUP_USE_AUTO_VALUES, DEFAULT_WAKEUP_USE_AUTO_VALUES),
            ): bool,
        }

        # Only show custom inputs when auto-values is disabled
        if not wakeup_use_auto:
            wakeup_schema_fields[
                vol.Optional(
                    CONF_WAKEUP_START_BRIGHTNESS,
                    default=_f(CONF_WAKEUP_START_BRIGHTNESS, DEFAULT_WAKEUP_START_BRIGHTNESS),
                )
            ] = NumberSelector(NumberSelectorConfig(min=1, max=50, step=1))
            wakeup_schema_fields[
                vol.Optional(
                    CONF_WAKEUP_END_KELVIN,
                    default=_f(CONF_WAKEUP_END_KELVIN, DEFAULT_WAKEUP_END_KELVIN),
                )
            ] = NumberSelector(NumberSelectorConfig(min=2000, max=6500, step=100))

        wakeup_schema = vol.Schema(wakeup_schema_fields)

        weather_schema = vol.Schema(
            {
                vol.Optional(
                    CONF_WEATHER_ENABLED,
                    default=_f(CONF_WEATHER_ENABLED, DEFAULT_WEATHER_ENABLED),
                ): bool,
                vol.Optional(
                    CONF_WEATHER_ENTITY,
                    description=_sensor_description(CONF_WEATHER_ENTITY),
                ): EntitySelector(
                    EntitySelectorConfig(domain="weather", multiple=False),
                ),
            }
        )

        # --- Assemble the full schema ---

        if _HAS_SECTIONS:
            # Build schema fields dynamically
            schema_fields: dict[Any, Any] = {}

            # Add area discovery section first if area is configured
            if has_area and area_discovery_schema_fields:
                area_discovery_schema = vol.Schema(area_discovery_schema_fields)
                schema_fields[vol.Required(SECTION_AREA)] = section(
                    area_discovery_schema, {"collapsed": False}
                )

            # Add remaining sections
            schema_fields[vol.Required(SECTION_DEVICES)] = section(
                devices_schema, {"collapsed": False}
            )
            schema_fields[vol.Required(SECTION_DAY)] = section(
                day_schema, {"collapsed": True}
            )
            schema_fields[vol.Required(SECTION_NIGHT)] = section(
                night_schema, {"collapsed": True}
            )
            schema_fields[vol.Required(SECTION_CIRCADIAN)] = section(
                circadian_schema, {"collapsed": True}
            )
            schema_fields[vol.Required(SECTION_TRANSITIONS)] = section(
                transitions_schema, {"collapsed": True}
            )
            schema_fields[vol.Required(SECTION_SLEEP)] = section(
                sleep_schema, {"collapsed": True}
            )
            schema_fields[vol.Required(SECTION_WAKEUP)] = section(
                wakeup_schema, {"collapsed": True}
            )
            schema_fields[vol.Required(SECTION_WEATHER)] = section(
                weather_schema, {"collapsed": True}
            )
            schema = vol.Schema(schema_fields)
        else:
            # Fallback for older HA versions without section support:
            # merge all sub-schemas into one flat schema.
            flat_fields: dict = {}
            # Add area discovery fields if area is configured
            if has_area and area_discovery_schema_fields:
                flat_fields.update(area_discovery_schema_fields)
            for sub in (
                devices_schema,
                day_schema,
                night_schema,
                circadian_schema,
                transitions_schema,
                sleep_schema,
                wakeup_schema,
                weather_schema,
            ):
                flat_fields.update(sub.schema)
            schema = vol.Schema(flat_fields)

        return self.async_show_form(
            step_id="init",
            data_schema=schema,
            errors=errors,
        )
