"""Pure parsing functions for Home Assistant entity states.

This module contains pure functions that parse Home Assistant state objects
into typed values. These functions have no side effects and can be tested
without any Home Assistant dependencies.

The functions are used by adapter classes (illuminance.py, weather.py, etc.)
to separate the I/O of reading from HA entities from the parsing logic.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.core import State

__all__ = [
    "parse_lux_state",
    "parse_weather_condition",
    "parse_sun_elevation",
    "is_motion_state_on",
    "calculate_compensated_lux",
    "get_weather_modifier",
]


def parse_lux_state(state: State | None) -> float | None:
    """Parse a light sensor state to a LUX float value.

    Args:
        state: Home Assistant state object from a light sensor entity

    Returns:
        LUX value as float, or None if state is unavailable/invalid

    Examples:
        >>> from unittest.mock import MagicMock
        >>> state = MagicMock()
        >>> state.state = "150.5"
        >>> parse_lux_state(state)
        150.5

        >>> parse_lux_state(None)
        None

        >>> state.state = "unknown"
        >>> parse_lux_state(state)
        None
    """
    if state is None:
        return None

    if state.state in (None, "unknown", "unavailable"):
        return None

    try:
        return float(state.state)
    except (TypeError, ValueError):
        return None


def parse_weather_condition(state: State | None) -> str | None:
    """Parse a weather entity state to a condition string.

    Args:
        state: Home Assistant state object from a weather entity

    Returns:
        Lowercase weather condition string (e.g., "sunny", "cloudy"),
        or None if state is unavailable/invalid

    Examples:
        >>> from unittest.mock import MagicMock
        >>> state = MagicMock()
        >>> state.state = "Sunny"
        >>> parse_weather_condition(state)
        'sunny'

        >>> parse_weather_condition(None)
        None
    """
    if state is None:
        return None

    if state.state in (None, "unknown", "unavailable"):
        return None

    return state.state.lower()


def parse_sun_elevation(state: State | None) -> float | None:
    """Parse sun entity state to extract elevation in degrees.

    Args:
        state: Home Assistant state object from sun.sun entity

    Returns:
        Elevation in degrees as float, or None if unavailable/invalid

    Examples:
        >>> from unittest.mock import MagicMock
        >>> state = MagicMock()
        >>> state.attributes = {"elevation": 45.5}
        >>> parse_sun_elevation(state)
        45.5

        >>> parse_sun_elevation(None)
        None

        >>> state.attributes = {}
        >>> parse_sun_elevation(state)
        None
    """
    if state is None:
        return None

    if not hasattr(state, "attributes"):
        return None

    elevation = state.attributes.get("elevation")
    if elevation is None:
        return None

    try:
        return float(elevation)
    except (TypeError, ValueError):
        return None


def is_motion_state_on(state: State | None) -> bool:
    """Check if a motion sensor state indicates motion is detected.

    Args:
        state: Home Assistant state object from a binary_sensor entity

    Returns:
        True if state is "on", False otherwise

    Examples:
        >>> from unittest.mock import MagicMock
        >>> state = MagicMock()
        >>> state.state = "on"
        >>> is_motion_state_on(state)
        True

        >>> state.state = "off"
        >>> is_motion_state_on(state)
        False

        >>> is_motion_state_on(None)
        False
    """
    if state is None:
        return False

    return state.state == "on"


def calculate_compensated_lux(
    lux_measured: float,
    lux_calibration: float | None,
    brightness_pct: int | None,
) -> float:
    """Calculate ambient LUX by subtracting estimated lamp contribution.

    When a light sensor is near controlled lights, the lights themselves
    contribute to the measured LUX. This function estimates and subtracts
    that contribution to get the true ambient (daylight) level.

    The lamp contribution is estimated linearly based on brightness:
    - At 100% brightness, the lamp contributes lux_calibration
    - At 50% brightness, it contributes lux_calibration * 0.5

    Args:
        lux_measured: Raw LUX reading from the sensor
        lux_calibration: Calibrated LUX contribution of lights at 100% brightness
        brightness_pct: Current brightness percentage of the controlled lights

    Returns:
        Estimated ambient LUX (always >= 0)

    Examples:
        >>> # No calibration data - return measured value
        >>> calculate_compensated_lux(100.0, None, 50)
        100.0

        >>> # With calibration and lights at 50%
        >>> # measured=100, lamp_contrib=40*0.5=20, ambient=80
        >>> calculate_compensated_lux(100.0, 40.0, 50)
        80.0

        >>> # Result clamped to minimum of 0
        >>> calculate_compensated_lux(10.0, 40.0, 100)
        0.0
    """
    if lux_calibration is None:
        return lux_measured

    if brightness_pct is None:
        return lux_measured

    # Linear estimate: lamp_lux = calibrated_lux * (brightness_pct / 100)
    lamp_contribution = lux_calibration * (brightness_pct / 100.0)
    ambient_lux = lux_measured - lamp_contribution

    return max(0.0, ambient_lux)


def get_weather_modifier(
    condition: str | None,
    modifiers: dict[str, float],
    default: float = 1.0,
    min_modifier: float = 0.5,
    max_modifier: float = 1.5,
) -> float:
    """Get brightness modifier for a weather condition.

    Looks up the configured modifier for the given weather condition,
    returning a default if not found. Result is clamped to a reasonable range.

    Args:
        condition: Weather condition string (e.g., "sunny", "cloudy", "rainy")
        modifiers: Dict mapping condition names to modifier values
        default: Default modifier if condition not found (default: 1.0)
        min_modifier: Minimum allowed modifier value (default: 0.5)
        max_modifier: Maximum allowed modifier value (default: 1.5)

    Returns:
        Brightness multiplier clamped to [min_modifier, max_modifier]

    Examples:
        >>> modifiers = {"sunny": 0.8, "cloudy": 1.2, "rainy": 1.3}
        >>> get_weather_modifier("sunny", modifiers)
        0.8

        >>> get_weather_modifier("unknown", modifiers)
        1.0

        >>> get_weather_modifier(None, modifiers)
        1.0

        >>> # Clamped to max
        >>> get_weather_modifier("sunny", {"sunny": 2.0})
        1.5
    """
    if condition is None:
        return default

    modifier = float(modifiers.get(condition, default))

    return max(min_modifier, min(max_modifier, modifier))
