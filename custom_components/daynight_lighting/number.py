"""Brightness dials for DayNight Lighting.

Night mode runs open loop: its brightness is a configured value, not the
result of a LUX measurement, so its dial holds an absolute brightness. The
configured night brightness is the starting point, used until somebody dials
in something else.

Day mode only has a single target when it runs without a LUX sensor on the
*fixed* fallback; there its dial also holds an absolute brightness, starting
from the configured fixed brightness. With a LUX sensor there is no single
value to show, so the dial does not apply.

The entities own the values, following the pattern of the Control Brightness
and Control Color switches: the mode handlers read them through
``SharedHandlerDeps``, and Home Assistant restores them across restarts.
"""

from __future__ import annotations

import logging

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import (
    CONF_DAY_FIXED_BRIGHTNESS_PCT,
    CONF_INSTANCE_NAME,
    CONF_NIGHT_BRIGHTNESS,
    DEFAULT_DAY_FIXED_BRIGHTNESS_PCT,
    DEFAULT_NIGHT_BRIGHTNESS,
    DOMAIN,
    MIN_DIAL_BRIGHTNESS_PCT,
    MIN_NIGHT_SENSOR_BRIGHTNESS_PCT,
    MODE_DAY,
    MODE_NIGHT,
    SIGNAL_MONITOR_UPDATE,
)
from .instance_data import (
    KEY_DAY_BRIGHTNESS,
    KEY_MAIN_SWITCH,
    KEY_NIGHT_BRIGHTNESS,
    instance_entity,
)

_LOGGER = logging.getLogger(__name__)

MIN_NIGHT_BRIGHTNESS = MIN_DIAL_BRIGHTNESS_PCT
MAX_NIGHT_BRIGHTNESS = 100
NIGHT_BRIGHTNESS_STEP = 5
DAY_BRIGHTNESS_STEP = 5


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the brightness dials from a config entry."""
    name = (
        config_entry.data.get(CONF_INSTANCE_NAME)
        or config_entry.options.get(CONF_INSTANCE_NAME)
        or "DayNight"
    )
    night = DayNightNightBrightnessNumber(config_entry, name)
    day = DayNightDayBrightnessNumber(config_entry, name)
    instance = hass.data.setdefault(DOMAIN, {}).setdefault(config_entry.entry_id, {})
    instance[KEY_NIGHT_BRIGHTNESS] = night
    instance[KEY_DAY_BRIGHTNESS] = day
    async_add_entities([night, day])


class _BrightnessDial(NumberEntity, RestoreEntity):
    """A dial one mode reads; changing it re-applies that mode at once."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_native_unit_of_measurement = "%"
    _attr_mode = NumberMode.SLIDER
    # The mode that reads this dial, the only one that has to act on it
    _applies_in: str

    def __init__(self, config_entry: ConfigEntry, name: str, key: str) -> None:
        self._config_entry = config_entry
        self._instance_name = name
        self._attr_unique_id = f"{config_entry.entry_id}-{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, config_entry.entry_id)},
            name=f"DayNight Lighting {name}",
        )

    def _write_state(self) -> None:
        """Publish the current value, if we are attached to Home Assistant."""
        if getattr(self, "hass", None) is not None:
            self.async_write_ha_state()

    def _write_and_apply(self) -> None:
        """Publish the new state and let the instance act on it."""
        hass = getattr(self, "hass", None)
        if hass is None:
            return
        self.async_write_ha_state()
        main_switch = instance_entity(
            hass, self._config_entry.entry_id, KEY_MAIN_SWITCH
        )
        if main_switch is None:
            return
        if main_switch.get_active_mode() == self._applies_in:
            main_switch.reapply_dialled_brightness()
        # The "Reset brightness" button mirrors the dial: after a step or a
        # slider change it must become pressable, so the monitors re-read.
        main_switch._notify_monitors()

    async def _async_restored_number(self) -> int | None:
        """The value stored before the restart, None if there is none."""
        last_state = await self.async_get_last_state()
        if last_state is None or last_state.state in (None, "", "unknown", "unavailable"):
            return None
        try:
            return int(float(last_state.state))
        except (TypeError, ValueError):
            return None


class DayNightNightBrightnessNumber(_BrightnessDial):
    """The night brightness currently in effect for one instance."""

    _attr_name = "Night brightness"
    _attr_icon = "mdi:weather-night"
    _attr_native_max_value = MAX_NIGHT_BRIGHTNESS
    _attr_native_step = NIGHT_BRIGHTNESS_STEP
    _applies_in = MODE_NIGHT

    def __init__(self, config_entry: ConfigEntry, name: str) -> None:
        super().__init__(config_entry, name, "night_brightness")
        self._dialled_in: int | None = None

    @property
    def configured_value(self) -> int:
        """The night brightness from the options, the starting point."""
        return int(
            self._config_entry.options.get(
                CONF_NIGHT_BRIGHTNESS, DEFAULT_NIGHT_BRIGHTNESS
            )
        )

    @property
    def native_min_value(self) -> int:
        """Lowest brightness the dial can reach.

        With a motion sensor the floor is 5 % so a motion-lit room keeps a
        guaranteed nightlight; without one it is the generic button floor. A
        configuration below the floor is a deliberate decision though, so it
        wins — otherwise the configured value could not even be displayed.
        """
        floor = (
            MIN_NIGHT_SENSOR_BRIGHTNESS_PCT
            if self._has_motion_sensor()
            else MIN_NIGHT_BRIGHTNESS
        )
        return min(floor, self.configured_value)

    def _has_motion_sensor(self) -> bool:
        """True when the instance drives night mode against a motion sensor.

        The main switch owns the resolution (manual sensor or area discovery),
        so we ask it rather than duplicating that logic here.
        """
        hass = getattr(self, "hass", None)
        if hass is None:
            return False
        main_switch = instance_entity(
            hass, self._config_entry.entry_id, KEY_MAIN_SWITCH
        )
        if main_switch is None or not hasattr(main_switch, "has_motion_sensor"):
            return False
        return main_switch.has_motion_sensor()

    @property
    def dialled_in_value(self) -> int | None:
        """The value somebody dialled in, None while none was.

        The night mode handler reads this and falls back to the configured
        value, so None and "equals the configured value" stay distinct.
        """
        return self._dialled_in

    @property
    def native_value(self) -> int:
        """What is in effect right now."""
        if self._dialled_in is None:
            return self.configured_value
        return self._dialled_in

    async def async_set_native_value(self, value: float) -> None:
        """Dial in a night brightness and apply it right away."""
        self.set_dialled_in(int(round(value)))

    def set_dialled_in(self, value: int) -> None:
        """Set the value, clamp it, write the state and re-apply the lights."""
        clamped = max(self.native_min_value, min(MAX_NIGHT_BRIGHTNESS, value))
        if clamped == self._dialled_in:
            return
        self._dialled_in = clamped
        _LOGGER.debug(
            "[%s] Night brightness dialled in: %d%% (configured %d%%)",
            self._instance_name,
            clamped,
            self.configured_value,
        )
        self._write_and_apply()

    def reset(self, *, apply: bool = True) -> None:
        """Fall back to the configured value.

        Args:
            apply: Re-apply the lights right away. False when the caller is
                about to apply the whole mode anyway, as on an options change.
        """
        if self._dialled_in is None:
            # Still publish: the configured value may have just changed
            self._write_state()
            return
        self._dialled_in = None
        _LOGGER.debug(
            "[%s] Night brightness reset to configured %d%%",
            self._instance_name,
            self.configured_value,
        )
        if apply:
            self._write_and_apply()
        else:
            self._write_state()

    async def async_added_to_hass(self) -> None:
        """Restore the dialled-in value across restarts."""
        await super().async_added_to_hass()
        restored = await self._async_restored_number()
        # A restored value equal to the configuration carries no information
        if restored is not None and restored != self.configured_value:
            self._dialled_in = max(
                self.native_min_value, min(MAX_NIGHT_BRIGHTNESS, restored)
            )


class DayNightDayBrightnessNumber(_BrightnessDial):
    """The day brightness currently in effect for one instance (fallback=fixed).

    Day mode without a LUX sensor and with the *fixed* fallback aims at a
    single value, so the dial holds an absolute brightness — like the night
    dial. The configured fixed brightness is the starting point, used until
    somebody dials in something else.
    """

    _attr_name = "Day brightness"
    _attr_icon = "mdi:white-balance-sunny"
    _attr_native_min_value = 0
    _attr_native_max_value = 100
    _attr_native_step = DAY_BRIGHTNESS_STEP
    _applies_in = MODE_DAY

    def __init__(self, config_entry: ConfigEntry, name: str) -> None:
        super().__init__(config_entry, name, "day_brightness")
        self._dialled_in: int | None = None

    @property
    def available(self) -> bool:
        """Unavailable while a LUX sensor drives the brightness instead.

        With a LUX sensor the day curve has no single fixed value, so this
        dial is meaningless: the "Day brightness" number would otherwise sit
        next to the LUX-derived target and show a value nothing reads.
        """
        return not self._has_lux_sensor()

    def _has_lux_sensor(self) -> bool:
        """True when the instance drives day mode against a LUX sensor.

        The main switch owns the resolution (manual sensor or area discovery),
        so we ask it rather than duplicating that logic here.
        """
        hass = getattr(self, "hass", None)
        if hass is None:
            return False
        main_switch = instance_entity(
            hass, self._config_entry.entry_id, KEY_MAIN_SWITCH
        )
        if main_switch is None or not hasattr(main_switch, "has_lux_sensor"):
            return False
        return main_switch.has_lux_sensor()

    @property
    def configured_value(self) -> int:
        """The fixed day brightness from the options, the starting point."""
        return int(
            self._config_entry.options.get(
                CONF_DAY_FIXED_BRIGHTNESS_PCT, DEFAULT_DAY_FIXED_BRIGHTNESS_PCT
            )
        )

    @property
    def dialled_in_value(self) -> int | None:
        """The value somebody dialled in, None while none was.

        The day mode handler reads this and falls back to the configured
        value, so None and "equals the configured value" stay distinct.
        """
        return self._dialled_in

    @property
    def native_value(self) -> int:
        """What is in effect right now."""
        if self._dialled_in is None:
            return self.configured_value
        return self._dialled_in

    async def async_set_native_value(self, value: float) -> None:
        """Dial in a day brightness and apply it right away."""
        self.set_dialled_in(int(round(value)))

    def set_dialled_in(self, value: int) -> None:
        """Set the value, clamp it, write the state and re-apply the lights."""
        clamped = max(0, min(100, value))
        if clamped == self._dialled_in:
            return
        self._dialled_in = clamped
        _LOGGER.debug(
            "[%s] Day brightness dialled in: %d%% (configured %d%%)",
            self._instance_name,
            clamped,
            self.configured_value,
        )
        self._write_and_apply()

    def reset(self, *, apply: bool = True) -> None:
        """Fall back to the configured fixed brightness.

        Args:
            apply: Re-apply the lights right away. False when the caller is
                about to apply the whole mode anyway, as on an options change.
        """
        if self._dialled_in is None:
            self._write_state()
            return
        self._dialled_in = None
        _LOGGER.debug(
            "[%s] Day brightness reset to configured %d%%",
            self._instance_name,
            self.configured_value,
        )
        if apply:
            self._write_and_apply()
        else:
            self._write_state()

    async def async_added_to_hass(self) -> None:
        """Restore the dialled-in value and follow the sensor resolution."""
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_MONITOR_UPDATE.format(entry_id=self._config_entry.entry_id),
                self._handle_update,
            )
        )
        restored = await self._async_restored_number()
        if restored is not None and restored != self.configured_value:
            self._dialled_in = max(0, min(100, restored))

    @callback
    def _handle_update(self) -> None:
        """Re-read availability: area discovery may resolve sensors late."""
        self.async_write_ha_state()
