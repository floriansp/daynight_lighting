"""The four mode handlers of one instance, typed.

A ``dict[str, Any]`` hid which handler offers what: the ramps' ``is_active``
or the night handler's ``handle_motion_on`` could only be reached through
``Any``. The instance always has exactly these four handlers, so they are
named fields and the dict view is derived for code that routes by mode.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

from ..const import MODE_DAY, MODE_NIGHT, MODE_SLEEP, MODE_WAKEUP
from .base import ModeHandler
from .day import DayModeHandler
from .night import NightModeHandler
from .sleep import SleepModeHandler
from .wakeup import WakeUpModeHandler

__all__ = ["ModeHandlers"]


@dataclass(frozen=True)
class ModeHandlers:
    """Day, night, sleep and wake-up handler of one instance."""

    day: DayModeHandler
    night: NightModeHandler
    sleep: SleepModeHandler
    wakeup: WakeUpModeHandler

    def by_mode(self) -> dict[str, ModeHandler]:
        """The handlers keyed by mode identifier."""
        return {
            MODE_DAY: self.day,
            MODE_NIGHT: self.night,
            MODE_SLEEP: self.sleep,
            MODE_WAKEUP: self.wakeup,
        }

    def for_mode(self, mode: str | None) -> ModeHandler | None:
        """The handler of *mode*, None for an unknown mode."""
        return self.by_mode().get(mode) if mode is not None else None

    def __iter__(self) -> Iterator[ModeHandler]:
        return iter(self.by_mode().values())
