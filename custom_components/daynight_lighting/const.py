"""Constants for the DayNight Lighting integration."""

DOMAIN = "daynight_lighting"

# Unique ID suffix for the main switch (used by services to resolve entity_id -> config entry)
MAIN_SWITCH_UNIQUE_ID_SUFFIX = "-main"

CONF_INSTANCE_NAME = "instance_name"
DEFAULT_INSTANCE_NAME = "default"

# Per-instance options (lights, sensors, area)
CONF_LIGHTS = "lights"
CONF_LIGHT_SENSOR = "light_sensor"
CONF_MOTION_SENSOR = "motion_sensor"
CONF_AREA_ID = "area_id"
CONF_USE_AREA_DISCOVERY = "use_area_discovery"  # Enable area-based auto-discovery
CONF_INCLUDED_LIGHTS = "included_lights"  # Area-based: lights explicitly selected for control
CONF_EXCLUDED_MOTION_SENSORS = "excluded_motion_sensors"  # Area-based: motion sensors to ignore during discovery

# Day mode options (LUX-based brightness)
CONF_LUX_ON = "lux_on"
CONF_LUX_OFF = "lux_off"
CONF_DAY_MIN_BRIGHTNESS = "day_min_brightness"
CONF_DAY_MAX_BRIGHTNESS = "day_max_brightness"

# Night mode options (motion-based)
CONF_NIGHT_MODE_START_TIME = "night_mode_start_time"  # "HH:MM" or "HH:MM:SS"
# When does night mode start: at sunset (sun below horizon) or at configured time only
CONF_NIGHT_MODE_START = "night_mode_start"  # "sun_below_horizon" | "at_time"
DEFAULT_NIGHT_MODE_START = "at_time"  # use configured time (e.g. 22:00) by default
CONF_MOTION_OFF_DELAY_MIN = "motion_off_delay_min"
CONF_NIGHT_BRIGHTNESS = "night_brightness"
# Floor for button dimming: a wall button must never be able to switch a light
# off. A dark staircase is worse than a bright one.
MIN_DIAL_BRIGHTNESS_PCT = 10
# Night-with-motion floor: a guaranteed nightlight, so a motion-lit room (e.g. a
# staircase) can never be dimmed into darkness. Separate from the generic button
# floor because it only applies when a motion sensor drives night mode.
MIN_NIGHT_SENSOR_BRIGHTNESS_PCT = 5
# When switching Day → Night without a trigger: leave lights as-is or turn off
CONF_ON_ENTER_NIGHT = "on_enter_night"  # "leave" | "turn_off"
DEFAULT_ON_ENTER_NIGHT = "leave"

# Circadian colour temperature (own implementation, no dependency on Adaptive Lighting addon)
CONF_CIRCADIAN_ENABLED = "circadian_enabled"
CONF_CIRCADIAN_MIN_KELVIN = "circadian_min_kelvin"  # warm, evening/night
CONF_CIRCADIAN_MAX_KELVIN = "circadian_max_kelvin"  # cool, midday
DEFAULT_CIRCADIAN_ENABLED = True
DEFAULT_CIRCADIAN_MIN_KELVIN = 2700
DEFAULT_CIRCADIAN_MAX_KELVIN = 5500

# Tick interval: how often the per-minute timer fires (seconds).
# Used as the basis for the max tick-transition duration.
TICK_INTERVAL_SECONDS = 60
# Max transition for tick context: must finish before the next tick.
MAX_TICK_TRANSITION_SECONDS = TICK_INTERVAL_SECONDS - 3

# Smooth transitions (seconds)
CONF_TRANSITION_SECONDS = "transition_seconds"          # Regular tick updates (day LUX, night circadian refresh)
CONF_INITIAL_TRANSITION_SECONDS = "initial_transition_seconds"  # First turn-on (motion ON, switch ON)
CONF_MODE_TRANSITION_SECONDS = "mode_transition_seconds"        # Day ↔ Night mode change
DEFAULT_TRANSITION_SECONDS = 0        # 0 = off (instant)
DEFAULT_INITIAL_TRANSITION_SECONDS = 0
DEFAULT_MODE_TRANSITION_SECONDS = 0

# LUX flapping detection (anti-oscillation)
CONF_LUX_SMOOTHING_SAMPLES = "lux_smoothing_samples"  # rolling average of N samples (1 = off)
CONF_BRIGHTNESS_CHANGE_THRESHOLD_PCT = "brightness_change_threshold_pct"  # min % change before sending
CONF_FLAPPING_FREEZE_MIN = "flapping_freeze_min"  # freeze after flapping detection
DEFAULT_LUX_SMOOTHING_SAMPLES = 3
DEFAULT_BRIGHTNESS_CHANGE_THRESHOLD_PCT = 3
DEFAULT_FLAPPING_FREEZE_MIN = 5

# Sensorless mode (fallback when sensors are missing or unavailable)
CONF_DAY_MODE_FALLBACK = "day_mode_fallback"  # what to do in day mode without LUX sensor
CONF_DAY_FIXED_BRIGHTNESS_PCT = "day_fixed_brightness_pct"  # fixed brightness for day mode fallback
CONF_NIGHT_MODE_FALLBACK = "night_mode_fallback"  # what to do in night mode without motion sensor

# Day mode fallback options
DAY_FALLBACK_SKIP = "skip"  # do nothing (default, current behaviour)
DAY_FALLBACK_FIXED = "fixed"  # fixed brightness + optional circadian
DAY_FALLBACK_CIRCADIAN_ONLY = "circadian_only"  # only colour, no brightness
DAY_FALLBACK_OFF = "off"  # turn lights off
DEFAULT_DAY_MODE_FALLBACK = DAY_FALLBACK_SKIP
DEFAULT_DAY_FIXED_BRIGHTNESS_PCT = 80

# Night mode fallback options
NIGHT_FALLBACK_SKIP = "skip"  # do nothing (default, current behaviour)
NIGHT_FALLBACK_ON = "on"  # turn lights on with night brightness
NIGHT_FALLBACK_OFF = "off"  # turn lights off
NIGHT_FALLBACK_KEEP = "keep"  # keep current state
DEFAULT_NIGHT_MODE_FALLBACK = NIGHT_FALLBACK_SKIP

# Defaults (used when option not set)
DEFAULT_LUX_ON = 10.0
DEFAULT_LUX_OFF = 100.0
DEFAULT_DAY_MIN_BRIGHTNESS = 0
DEFAULT_DAY_MAX_BRIGHTNESS = 100
DEFAULT_NIGHT_MODE_START_TIME = (22, 0)  # 22:00
DEFAULT_NIGHT_MODE_START_TIME_STR = "22:00"
DEFAULT_MOTION_OFF_DELAY_MIN = 5
DEFAULT_NIGHT_BRIGHTNESS = 100
DEFAULT_USE_AREA_DISCOVERY = False  # Default to False for backward compatibility

# ---------------------------------------------------------------------------
#  Mode identifiers
# ---------------------------------------------------------------------------

MODE_NIGHT = "night"
MODE_WAKEUP = "wakeup"
MODE_DAY = "day"
MODE_SLEEP = "sleep"

# ---------------------------------------------------------------------------
#  Sleep mode configuration
# ---------------------------------------------------------------------------

CONF_SLEEP_ENABLED = "sleep_enabled"
CONF_SLEEP_START_TIME = "sleep_start_time"
CONF_SLEEP_DURATION_MIN = "sleep_duration_min"  # Optional: explicit duration in minutes
CONF_SLEEP_TARGET_BRIGHTNESS = "sleep_target_brightness"
CONF_SLEEP_TARGET_KELVIN = "sleep_target_kelvin"
CONF_SLEEP_USE_AUTO_VALUES = "sleep_use_auto_values"

DEFAULT_SLEEP_ENABLED = False
DEFAULT_SLEEP_START_TIME = (21, 0)  # 21:00
DEFAULT_SLEEP_START_TIME_STR = "21:00"
DEFAULT_SLEEP_DURATION_MIN = 60  # 1 hour default (Sleep Mode 2.0 requires explicit duration)
DEFAULT_SLEEP_TARGET_BRIGHTNESS = 20
DEFAULT_SLEEP_TARGET_KELVIN = 2200
DEFAULT_SLEEP_USE_AUTO_VALUES = True

# ---------------------------------------------------------------------------
#  Wake-up mode configuration
# ---------------------------------------------------------------------------

CONF_WAKEUP_ENABLED = "wakeup_enabled"
CONF_WAKEUP_TIME = "wakeup_time"  # When wake-up completes (day mode starts)
CONF_WAKEUP_DURATION_MIN = "wakeup_duration_min"
CONF_WAKEUP_START_BRIGHTNESS = "wakeup_start_brightness"
CONF_WAKEUP_USE_AUTO_VALUES = "wakeup_use_auto_values"
CONF_WAKEUP_END_KELVIN = "wakeup_end_kelvin"

DEFAULT_WAKEUP_ENABLED = False
DEFAULT_WAKEUP_TIME = (7, 0)  # 07:00
DEFAULT_WAKEUP_TIME_STR = "07:00"
DEFAULT_WAKEUP_DURATION_MIN = 30
DEFAULT_WAKEUP_START_BRIGHTNESS = 1
DEFAULT_WAKEUP_USE_AUTO_VALUES = True
DEFAULT_WAKEUP_END_KELVIN = 5500

# ---------------------------------------------------------------------------
#  Weather brightness configuration
# ---------------------------------------------------------------------------

CONF_WEATHER_ENABLED = "weather_brightness_enabled"
CONF_WEATHER_ENTITY = "weather_entity"
CONF_WEATHER_BRIGHTNESS_MODIFIERS = "weather_brightness_modifiers"

DEFAULT_WEATHER_ENABLED = False
DEFAULT_WEATHER_MODIFIERS = {
    "clear-night": 1.0,
    "cloudy": 1.0,
    "exceptional": 1.0,
    "fog": 1.3,
    "hail": 1.2,
    "lightning": 1.2,
    "lightning-rainy": 1.2,
    "partlycloudy": 0.85,
    "pouring": 1.3,
    "rainy": 1.2,
    "snowy": 1.2,
    "snowy-rainy": 1.2,
    "sunny": 0.7,
    "windy": 1.0,
    "windy-variant": 1.0,
}

# ---------------------------------------------------------------------------
#  Monitoring (sensor platform)
# ---------------------------------------------------------------------------

# Fired on the event bus whenever an instance changes mode
EVENT_MODE_CHANGED = f"{DOMAIN}_mode_changed"

# Dispatcher signal telling the sensors of one instance to re-read
SIGNAL_MONITOR_UPDATE = DOMAIN + "_monitor_update_{entry_id}"
