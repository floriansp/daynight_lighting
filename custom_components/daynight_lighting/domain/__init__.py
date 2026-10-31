"""Pure domain layer for DayNight Lighting.

This package contains business logic that is completely independent of
Home Assistant. All functions are pure (no side effects, no I/O) and
can be unit tested without any framework dependencies.
"""

from __future__ import annotations

__all__ = [
    # Models
    "Mode",
    "CircadianResult",
    # Brightness functions
    "brightness_to_pct",
    "lux_to_brightness_pct",
    "apply_weather_modifier",
    "ramp_value",
    # Color functions
    "calculate_kelvin_from_elevation",
    # Schedule functions
    "is_in_time_window",
    "calculate_progress_ratio",
    "calculate_time_after",
    "calculate_time_before",
    "ModeDeterminationContext",
    "determine_mode",
]

from .models import Mode, CircadianResult
from .brightness import (
    apply_weather_modifier,
    brightness_to_pct,
    lux_to_brightness_pct,
    ramp_value,
)
from .color import calculate_kelvin_from_elevation
from .schedule import (
    is_in_time_window,
    calculate_progress_ratio,
    calculate_time_after,
    calculate_time_before,
    ModeDeterminationContext,
    determine_mode,
)
