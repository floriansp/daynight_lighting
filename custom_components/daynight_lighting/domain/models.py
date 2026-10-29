"""Pure data models for DayNight Lighting domain layer.

These models have no dependencies on Home Assistant and represent
core domain concepts in a testable, serializable form.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Mode(Enum):
    """Operating modes for DayNight Lighting."""

    DAY = "day"
    NIGHT = "night"
    SLEEP = "sleep"
    WAKEUP = "wakeup"


@dataclass(frozen=True)
class CircadianResult:
    """Result of circadian color temperature calculation.

    Contains both the computed Kelvin value and sun metadata.
    """

    kelvin: int
    sun_elevation: float | None = None
    source: str = "circadian"  # "circadian", "min_fallback", "max_fallback"
