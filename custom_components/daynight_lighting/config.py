"""Typed configuration classes for DayNight Lighting.

This module provides type-safe configuration objects to replace the raw
dict[str, Any] options passing used throughout the integration.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Re-export all config classes for convenient imports
__all__ = [
    "DayModeConfig",
    "NightModeConfig",
    "CircadianConfig",
    "SleepModeConfig",
    "WakeUpModeConfig",
    "IlluminanceConfig",
    "WeatherConfig",
    "TransitionConfig",
    "DayNightConfig",
]

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
    CONF_LIGHTS,
    CONF_LIGHT_SENSOR,
    CONF_LUX_OFF,
    CONF_LUX_ON,
    CONF_LUX_SMOOTHING_SAMPLES,
    CONF_MODE_TRANSITION_SECONDS,
    CONF_MOTION_OFF_DELAY_MIN,
    CONF_MOTION_SENSOR,
    CONF_NIGHT_BRIGHTNESS,
    CONF_NIGHT_MODE_FALLBACK,
    CONF_NIGHT_MODE_START,
    CONF_NIGHT_MODE_START_TIME,
    CONF_ON_ENTER_NIGHT,
    CONF_SLEEP_DURATION_MIN,
    CONF_SLEEP_ENABLED,
    CONF_SLEEP_START_TIME,
    CONF_SLEEP_TARGET_BRIGHTNESS,
    CONF_SLEEP_TARGET_KELVIN,
    CONF_SLEEP_USE_AUTO_VALUES,
    CONF_TRANSITION_SECONDS,
    CONF_USE_AREA_DISCOVERY,
    CONF_WAKEUP_DURATION_MIN,
    CONF_WAKEUP_ENABLED,
    CONF_WAKEUP_END_KELVIN,
    CONF_WAKEUP_START_BRIGHTNESS,
    CONF_WAKEUP_TIME,
    CONF_WAKEUP_USE_AUTO_VALUES,
    CONF_WEATHER_BRIGHTNESS_MODIFIERS,
    CONF_WEATHER_ENABLED,
    CONF_WEATHER_ENTITY,
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
    DEFAULT_LUX_OFF,
    DEFAULT_LUX_ON,
    DEFAULT_LUX_SMOOTHING_SAMPLES,
    DEFAULT_MODE_TRANSITION_SECONDS,
    DEFAULT_MOTION_OFF_DELAY_MIN,
    DEFAULT_NIGHT_BRIGHTNESS,
    DEFAULT_NIGHT_MODE_FALLBACK,
    DEFAULT_NIGHT_MODE_START,
    DEFAULT_NIGHT_MODE_START_TIME,
    DEFAULT_ON_ENTER_NIGHT,
    DEFAULT_SLEEP_DURATION_MIN,
    DEFAULT_SLEEP_ENABLED,
    DEFAULT_SLEEP_START_TIME,
    DEFAULT_SLEEP_TARGET_BRIGHTNESS,
    DEFAULT_SLEEP_TARGET_KELVIN,
    DEFAULT_SLEEP_USE_AUTO_VALUES,
    DEFAULT_TRANSITION_SECONDS,
    DEFAULT_USE_AREA_DISCOVERY,
    DEFAULT_WAKEUP_DURATION_MIN,
    DEFAULT_WAKEUP_ENABLED,
    DEFAULT_WAKEUP_END_KELVIN,
    DEFAULT_WAKEUP_START_BRIGHTNESS,
    DEFAULT_WAKEUP_TIME,
    DEFAULT_WAKEUP_USE_AUTO_VALUES,
    DEFAULT_WEATHER_ENABLED,
    DEFAULT_WEATHER_MODIFIERS,
)
from .utils import (
    dedupe_entity_ids,
    extract_entity_id,
    extract_entity_ids,
    parse_time_string,
)


@dataclass(frozen=True)
class DayModeConfig:
    """Configuration for day mode operation."""

    lux_on: float = DEFAULT_LUX_ON
    lux_off: float = DEFAULT_LUX_OFF
    min_brightness: int = DEFAULT_DAY_MIN_BRIGHTNESS
    max_brightness: int = DEFAULT_DAY_MAX_BRIGHTNESS
    fallback: str = DEFAULT_DAY_MODE_FALLBACK
    fixed_brightness_pct: int = DEFAULT_DAY_FIXED_BRIGHTNESS_PCT

    def __post_init__(self) -> None:
        """Validate configuration values."""
        if self.lux_on >= self.lux_off:
            raise ValueError(
                f"DayModeConfig: lux_on ({self.lux_on}) must be < lux_off ({self.lux_off})"
            )
        if not (0 <= self.min_brightness <= 100):
            raise ValueError(
                f"DayModeConfig: min_brightness ({self.min_brightness}) must be 0-100"
            )
        if not (0 <= self.max_brightness <= 100):
            raise ValueError(
                f"DayModeConfig: max_brightness ({self.max_brightness}) must be 0-100"
            )
        if self.min_brightness > self.max_brightness:
            raise ValueError(
                f"DayModeConfig: min_brightness ({self.min_brightness}) must be <= "
                f"max_brightness ({self.max_brightness})"
            )
        if not (0 <= self.fixed_brightness_pct <= 100):
            raise ValueError(
                f"DayModeConfig: fixed_brightness_pct ({self.fixed_brightness_pct}) must be 0-100"
            )


@dataclass(frozen=True)
class NightModeConfig:
    """Configuration for night mode operation."""

    start_time: tuple[int, int] = field(default_factory=lambda: DEFAULT_NIGHT_MODE_START_TIME)
    start_trigger: str = DEFAULT_NIGHT_MODE_START
    motion_off_delay_min: int = DEFAULT_MOTION_OFF_DELAY_MIN
    brightness: int = DEFAULT_NIGHT_BRIGHTNESS
    on_enter_night: str = DEFAULT_ON_ENTER_NIGHT
    fallback: str = DEFAULT_NIGHT_MODE_FALLBACK

    def __post_init__(self) -> None:
        """Validate configuration values."""
        if not (0 <= self.brightness <= 100):
            raise ValueError(
                f"NightModeConfig: brightness ({self.brightness}) must be 0-100"
            )
        if self.motion_off_delay_min < 0:
            raise ValueError(
                f"NightModeConfig: motion_off_delay_min ({self.motion_off_delay_min}) must be >= 0"
            )


@dataclass(frozen=True)
class CircadianConfig:
    """Configuration for circadian color temperature."""

    enabled: bool = DEFAULT_CIRCADIAN_ENABLED
    min_kelvin: int = DEFAULT_CIRCADIAN_MIN_KELVIN
    max_kelvin: int = DEFAULT_CIRCADIAN_MAX_KELVIN

    def __post_init__(self) -> None:
        """Validate configuration values."""
        if self.min_kelvin >= self.max_kelvin:
            raise ValueError(
                f"CircadianConfig: min_kelvin ({self.min_kelvin}) must be < "
                f"max_kelvin ({self.max_kelvin})"
            )
        if self.min_kelvin < 1000:
            raise ValueError(
                f"CircadianConfig: min_kelvin ({self.min_kelvin}) must be >= 1000K"
            )


@dataclass(frozen=True)
class SleepModeConfig:
    """Configuration for sleep mode operation."""

    enabled: bool = DEFAULT_SLEEP_ENABLED
    start_time: tuple[int, int] = field(default_factory=lambda: DEFAULT_SLEEP_START_TIME)
    duration_min: int = DEFAULT_SLEEP_DURATION_MIN
    target_brightness: int = DEFAULT_SLEEP_TARGET_BRIGHTNESS
    target_kelvin: int = DEFAULT_SLEEP_TARGET_KELVIN
    use_auto_values: bool = DEFAULT_SLEEP_USE_AUTO_VALUES

    def __post_init__(self) -> None:
        """Validate configuration values."""
        if not (0 <= self.target_brightness <= 100):
            raise ValueError(
                f"SleepModeConfig: target_brightness ({self.target_brightness}) must be 0-100"
            )
        if self.target_kelvin < 1000:
            raise ValueError(
                f"SleepModeConfig: target_kelvin ({self.target_kelvin}) must be >= 1000K"
            )
        if self.duration_min < 1:
            raise ValueError(
                f"SleepModeConfig: duration_min ({self.duration_min}) must be >= 1"
            )


@dataclass(frozen=True)
class WakeUpModeConfig:
    """Configuration for wake-up mode operation."""

    enabled: bool = DEFAULT_WAKEUP_ENABLED
    wake_time: tuple[int, int] = field(default_factory=lambda: DEFAULT_WAKEUP_TIME)
    duration_min: int = DEFAULT_WAKEUP_DURATION_MIN
    start_brightness: int = DEFAULT_WAKEUP_START_BRIGHTNESS
    use_auto_values: bool = DEFAULT_WAKEUP_USE_AUTO_VALUES
    end_kelvin: int = DEFAULT_WAKEUP_END_KELVIN

    def __post_init__(self) -> None:
        """Validate configuration values."""
        if not (0 <= self.start_brightness <= 100):
            raise ValueError(
                f"WakeUpModeConfig: start_brightness ({self.start_brightness}) must be 0-100"
            )
        if self.duration_min < 1:
            raise ValueError(
                f"WakeUpModeConfig: duration_min ({self.duration_min}) must be >= 1"
            )
        if self.end_kelvin < 1000:
            raise ValueError(
                f"WakeUpModeConfig: end_kelvin ({self.end_kelvin}) must be >= 1000K"
            )


@dataclass(frozen=True)
class IlluminanceConfig:
    """Configuration for illuminance sensor handling."""

    smoothing_samples: int = DEFAULT_LUX_SMOOTHING_SAMPLES
    brightness_change_threshold_pct: int = DEFAULT_BRIGHTNESS_CHANGE_THRESHOLD_PCT
    flapping_freeze_min: int = DEFAULT_FLAPPING_FREEZE_MIN

    def __post_init__(self) -> None:
        """Validate configuration values."""
        if self.smoothing_samples < 1:
            raise ValueError(
                f"IlluminanceConfig: smoothing_samples ({self.smoothing_samples}) must be >= 1"
            )
        if not (0 <= self.brightness_change_threshold_pct <= 100):
            raise ValueError(
                f"IlluminanceConfig: brightness_change_threshold_pct "
                f"({self.brightness_change_threshold_pct}) must be 0-100"
            )
        if self.flapping_freeze_min < 0:
            raise ValueError(
                f"IlluminanceConfig: flapping_freeze_min ({self.flapping_freeze_min}) must be >= 0"
            )


@dataclass(frozen=True)
class WeatherConfig:
    """Configuration for weather-based brightness adjustment."""

    enabled: bool = DEFAULT_WEATHER_ENABLED
    entity: str | None = None
    brightness_modifiers: dict[str, float] = field(default_factory=lambda: DEFAULT_WEATHER_MODIFIERS.copy())


@dataclass(frozen=True)
class TransitionConfig:
    """Configuration for transition timings."""

    regular: int = DEFAULT_TRANSITION_SECONDS
    initial: int = DEFAULT_INITIAL_TRANSITION_SECONDS
    mode: int = DEFAULT_MODE_TRANSITION_SECONDS


@dataclass(frozen=True)
class DayNightConfig:
    """Complete configuration for a DayNight Lighting instance."""

    instance_name: str = DEFAULT_INSTANCE_NAME
    lights: list[str] = field(default_factory=list)
    area_id: str | None = None
    light_sensor: str | list[str] | None = None
    motion_sensor: str | list[str] | None = None

    # Area-based discovery settings
    use_area_discovery: bool = DEFAULT_USE_AREA_DISCOVERY
    included_lights: list[str] = field(default_factory=list)
    excluded_motion_sensors: list[str] = field(default_factory=list)

    day_mode: DayModeConfig = field(default_factory=DayModeConfig)
    night_mode: NightModeConfig = field(default_factory=NightModeConfig)
    circadian: CircadianConfig = field(default_factory=CircadianConfig)
    sleep_mode: SleepModeConfig = field(default_factory=SleepModeConfig)
    wake_up_mode: WakeUpModeConfig = field(default_factory=WakeUpModeConfig)
    illuminance: IlluminanceConfig = field(default_factory=IlluminanceConfig)
    weather: WeatherConfig = field(default_factory=WeatherConfig)
    transitions: TransitionConfig = field(default_factory=TransitionConfig)

    def is_area_based(self) -> bool:
        """Check if this config uses area-based discovery.

        Returns:
            True if area discovery is enabled and area_id is configured.
        """
        return self.use_area_discovery and self.area_id is not None

    def get_effective_lights(self, hass: Any | None = None) -> list[str]:
        """Get the list of lights to control.

        For area-based mode:
        - If included_lights is empty, all (non-group) area lights are controlled
        - If included_lights has entries, only those are controlled

        For legacy mode:
        - Returns the lights list from configuration

        Args:
            hass: Needed to discover the area lights when ``included_lights``
                is empty. Without it (pure config context) an empty
                ``included_lights`` yields an empty list.

        Returns:
            List of light entity IDs to control, deduplicated case-insensitively.
        """
        if self.is_area_based():
            if self.included_lights:
                return dedupe_entity_ids(self.included_lights)
            if hass is None:
                return []
            # Leave included_lights empty to control every real light in the
            # area; the discovery skips virtual groups (Hue rooms/zones).
            from .area_discovery import get_lights_in_area

            return get_lights_in_area(hass, self.area_id, self.instance_name)
        # Legacy mode: the explicit ``lights`` list. Fall back to
        # ``included_lights`` so a config where discovery was just disabled
        # (the selection is still recorded under the area section) keeps
        # controlling the same lights instead of silently going empty.
        return dedupe_entity_ids(self.lights or self.included_lights)

    @classmethod
    def from_ha_options(
        cls, options: dict[str, Any], data_area_id: str | None = None
    ) -> DayNightConfig:
        """Create typed configuration from Home Assistant options dict.

        Args:
            options: Raw options dict from HA config entry
            data_area_id: Optional area_id from config_entry.data (fallback if not in options)

        Returns:
            DayNightConfig with all values properly typed
        """
        # Core settings
        instance_name = options.get(CONF_INSTANCE_NAME, DEFAULT_INSTANCE_NAME)
        lights = options.get(CONF_LIGHTS, [])
        if isinstance(lights, str):
            lights = [lights]
        lights = [str(light) for light in lights if light]

        # area_id may be in options (after options flow) or in data (initial setup)
        area_id = options.get(CONF_AREA_ID)
        if area_id and isinstance(area_id, list):
            area_id = area_id[0] if area_id else None
        # Fallback to data_area_id if not found in options
        if area_id is None:
            area_id = data_area_id

        # Area-based discovery settings
        # If area_id is present and use_area_discovery hasn't been explicitly set,
        # default to True (user selected an area during setup, likely wants area discovery)
        if CONF_USE_AREA_DISCOVERY in options:
            use_area_discovery = bool(options.get(CONF_USE_AREA_DISCOVERY))
        else:
            # Default to True if area_id is set, False otherwise
            use_area_discovery = area_id is not None

        included_lights = options.get(CONF_INCLUDED_LIGHTS, [])
        if isinstance(included_lights, str):
            included_lights = [included_lights]
        included_lights = [str(light) for light in included_lights if light]

        excluded_motion_sensors = options.get(CONF_EXCLUDED_MOTION_SENSORS, [])
        if isinstance(excluded_motion_sensors, str):
            excluded_motion_sensors = [excluded_motion_sensors]
        excluded_motion_sensors = [str(s) for s in excluded_motion_sensors if s]

        light_sensor = extract_entity_ids(options, CONF_LIGHT_SENSOR) or None
        motion_sensor = extract_entity_ids(options, CONF_MOTION_SENSOR) or None

        # Day mode config
        day_mode = DayModeConfig(
            lux_on=float(options.get(CONF_LUX_ON, DEFAULT_LUX_ON)),
            lux_off=float(options.get(CONF_LUX_OFF, DEFAULT_LUX_OFF)),
            min_brightness=int(options.get(CONF_DAY_MIN_BRIGHTNESS, DEFAULT_DAY_MIN_BRIGHTNESS)),
            max_brightness=int(options.get(CONF_DAY_MAX_BRIGHTNESS, DEFAULT_DAY_MAX_BRIGHTNESS)),
            fallback=str(options.get(CONF_DAY_MODE_FALLBACK, DEFAULT_DAY_MODE_FALLBACK)),
            fixed_brightness_pct=int(options.get(CONF_DAY_FIXED_BRIGHTNESS_PCT, DEFAULT_DAY_FIXED_BRIGHTNESS_PCT)),
        )

        # Night mode config
        night_start_time = parse_time_string(
            options.get(CONF_NIGHT_MODE_START_TIME),
            DEFAULT_NIGHT_MODE_START_TIME,
        )
        night_mode = NightModeConfig(
            start_time=night_start_time,
            start_trigger=str(options.get(CONF_NIGHT_MODE_START, DEFAULT_NIGHT_MODE_START)),
            motion_off_delay_min=int(options.get(CONF_MOTION_OFF_DELAY_MIN, DEFAULT_MOTION_OFF_DELAY_MIN)),
            brightness=int(options.get(CONF_NIGHT_BRIGHTNESS, DEFAULT_NIGHT_BRIGHTNESS)),
            on_enter_night=str(options.get(CONF_ON_ENTER_NIGHT, DEFAULT_ON_ENTER_NIGHT)),
            fallback=str(options.get(CONF_NIGHT_MODE_FALLBACK, DEFAULT_NIGHT_MODE_FALLBACK)),
        )

        # Circadian config
        circadian = CircadianConfig(
            enabled=bool(options.get(CONF_CIRCADIAN_ENABLED, DEFAULT_CIRCADIAN_ENABLED)),
            min_kelvin=int(options.get(CONF_CIRCADIAN_MIN_KELVIN, DEFAULT_CIRCADIAN_MIN_KELVIN)),
            max_kelvin=int(options.get(CONF_CIRCADIAN_MAX_KELVIN, DEFAULT_CIRCADIAN_MAX_KELVIN)),
        )

        # Sleep mode config
        sleep_start_time = parse_time_string(
            options.get(CONF_SLEEP_START_TIME),
            DEFAULT_SLEEP_START_TIME,
        )
        sleep_mode = SleepModeConfig(
            enabled=bool(options.get(CONF_SLEEP_ENABLED, DEFAULT_SLEEP_ENABLED)),
            start_time=sleep_start_time,
            duration_min=int(options.get(CONF_SLEEP_DURATION_MIN, DEFAULT_SLEEP_DURATION_MIN)),
            target_brightness=int(options.get(CONF_SLEEP_TARGET_BRIGHTNESS, DEFAULT_SLEEP_TARGET_BRIGHTNESS)),
            target_kelvin=int(options.get(CONF_SLEEP_TARGET_KELVIN, DEFAULT_SLEEP_TARGET_KELVIN)),
            use_auto_values=bool(options.get(CONF_SLEEP_USE_AUTO_VALUES, DEFAULT_SLEEP_USE_AUTO_VALUES)),
        )

        # Wake-up mode config
        wake_time = parse_time_string(
            options.get(CONF_WAKEUP_TIME),
            DEFAULT_WAKEUP_TIME,
        )
        wake_up_mode = WakeUpModeConfig(
            enabled=bool(options.get(CONF_WAKEUP_ENABLED, DEFAULT_WAKEUP_ENABLED)),
            wake_time=wake_time,
            duration_min=int(options.get(CONF_WAKEUP_DURATION_MIN, DEFAULT_WAKEUP_DURATION_MIN)),
            start_brightness=int(options.get(CONF_WAKEUP_START_BRIGHTNESS, DEFAULT_WAKEUP_START_BRIGHTNESS)),
            use_auto_values=bool(options.get(CONF_WAKEUP_USE_AUTO_VALUES, DEFAULT_WAKEUP_USE_AUTO_VALUES)),
            end_kelvin=int(options.get(CONF_WAKEUP_END_KELVIN, DEFAULT_WAKEUP_END_KELVIN)),
        )

        # Illuminance config
        illuminance = IlluminanceConfig(
            smoothing_samples=int(options.get(CONF_LUX_SMOOTHING_SAMPLES, DEFAULT_LUX_SMOOTHING_SAMPLES)),
            brightness_change_threshold_pct=int(options.get(CONF_BRIGHTNESS_CHANGE_THRESHOLD_PCT, DEFAULT_BRIGHTNESS_CHANGE_THRESHOLD_PCT)),
            flapping_freeze_min=int(options.get(CONF_FLAPPING_FREEZE_MIN, DEFAULT_FLAPPING_FREEZE_MIN)),
        )

        # Weather config
        weather_modifiers = options.get(CONF_WEATHER_BRIGHTNESS_MODIFIERS, DEFAULT_WEATHER_MODIFIERS.copy())
        weather = WeatherConfig(
            enabled=bool(options.get(CONF_WEATHER_ENABLED, DEFAULT_WEATHER_ENABLED)),
            entity=extract_entity_id(options, CONF_WEATHER_ENTITY),
            brightness_modifiers=dict(weather_modifiers) if isinstance(weather_modifiers, dict) else DEFAULT_WEATHER_MODIFIERS.copy(),
        )

        # Transitions config
        transitions = TransitionConfig(
            regular=int(options.get(CONF_TRANSITION_SECONDS, DEFAULT_TRANSITION_SECONDS)),
            initial=int(options.get(CONF_INITIAL_TRANSITION_SECONDS, DEFAULT_INITIAL_TRANSITION_SECONDS)),
            mode=int(options.get(CONF_MODE_TRANSITION_SECONDS, DEFAULT_MODE_TRANSITION_SECONDS)),
        )

        return cls(
            instance_name=instance_name,
            lights=lights,
            area_id=area_id,
            light_sensor=light_sensor,
            motion_sensor=motion_sensor,
            use_area_discovery=use_area_discovery,
            included_lights=included_lights,
            excluded_motion_sensors=excluded_motion_sensors,
            day_mode=day_mode,
            night_mode=night_mode,
            circadian=circadian,
            sleep_mode=sleep_mode,
            wake_up_mode=wake_up_mode,
            illuminance=illuminance,
            weather=weather,
            transitions=transitions,
        )
