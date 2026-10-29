"""Pure brightness calculation functions for DayNight Lighting.

These are the formulas the mode handlers apply. All functions in this module
are pure - they have no side effects, no I/O, and depend only on their
inputs. They can be unit tested without any Home Assistant dependencies.
"""

from __future__ import annotations


def brightness_to_pct(brightness: int | None) -> int | None:
    """Convert HA brightness (0-255) to percentage (0-100); None stays None.

    Examples:
        >>> brightness_to_pct(128)
        50
        >>> brightness_to_pct(None) is None
        True
        >>> brightness_to_pct(255)
        100
    """
    if brightness is None:
        return None
    return max(0, min(100, round(100 * brightness / 255)))


def lux_to_brightness_pct(
    lux: float,
    lux_on: float,
    lux_off: float,
    day_min: int,
    day_max: int,
) -> int | None:
    """Compute day brightness 0-100 from LUX (linear); None means off.

    At or below *lux_on* the room is dark and gets *day_max*; at or above
    *lux_off* it is bright and gets *day_min*, or off when that is 0. In
    between the brightness falls linearly.

    Examples:
        >>> lux_to_brightness_pct(5, 10, 100, 10, 100)
        100
        >>> lux_to_brightness_pct(55, 10, 100, 10, 100)
        55
        >>> lux_to_brightness_pct(150, 10, 100, 0, 100) is None
        True
    """
    if lux <= lux_on:
        return day_max
    if lux >= lux_off:
        return day_min if day_min > 0 else None
    lux_range = lux_off - lux_on
    slope = (day_min - day_max) / lux_range
    intercept = (-slope * lux_on) + day_max
    value = (slope * lux) + intercept
    return max(0, min(100, int(round(value))))


def apply_weather_modifier(
    brightness_pct: int,
    modifier: float,
    min_brightness: int,
    max_brightness: int,
) -> int:
    """Scale a day brightness by a weather modifier, kept within day min/max.

    The product is truncated, not rounded, so a modifier never lifts a value
    past the next whole percent.

    Examples:
        >>> apply_weather_modifier(50, 1.2, 10, 100)
        60
        >>> apply_weather_modifier(50, 0.7, 40, 100)
        40
        >>> apply_weather_modifier(99, 1.3, 10, 100)
        100
    """
    return max(min_brightness, min(max_brightness, int(brightness_pct * modifier)))


def ramp_value(start: int, end: int, progress: float) -> int:
    """Value at *progress* (0.0-1.0) along a linear ramp from *start* to *end*.

    Used by the sleep and wake-up ramps for brightness and colour
    temperature. Truncates towards zero; callers clamp to their own range.

    Examples:
        >>> ramp_value(80, 10, 0.5)
        45
        >>> ramp_value(1, 100, 0.25)
        25
        >>> ramp_value(2700, 2200, 1.0)
        2200
    """
    return int(start + (end - start) * progress)
