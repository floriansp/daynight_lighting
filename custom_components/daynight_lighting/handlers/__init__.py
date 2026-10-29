"""Mode handlers package for DayNight Lighting.

This package contains mode-specific handler classes that implement the
ModeHandler protocol. Each handler encapsulates the behavior for a
specific mode (day, night, sleep, wake-up).

The handlers are split into separate modules for maintainability:
- base: Protocol definition and shared utilities
- day: DayModeHandler (LUX-based brightness, circadian color)
- night: NightModeHandler (motion-based on/off, fixed brightness)
- sleep: SleepModeHandler (gradual dimming)
- wakeup: WakeUpModeHandler (gradual brightening)
"""

from .base import ModeHandler, brightness_to_pct, lux_to_brightness_pct
from .day import DayModeHandler
from .night import NightModeHandler
from .sleep import SleepModeHandler
from .wakeup import WakeUpModeHandler

__all__ = [
    "ModeHandler",
    "DayModeHandler",
    "NightModeHandler",
    "SleepModeHandler",
    "WakeUpModeHandler",
    "brightness_to_pct",
    "lux_to_brightness_pct",
]
