"""The brightness dials of an instance, as the switch sees them.

Night and day each have a number entity that remembers a brightness somebody
dialled in. The switch needs the dialled-in value, to reset a dial and to move
it; the mirrored night/day code this replaces lived in six methods.
"""

from __future__ import annotations

from typing import Callable, Protocol

from .const import MODE_DAY, MODE_NIGHT
from .instance_data import KEY_DAY_BRIGHTNESS, KEY_NIGHT_BRIGHTNESS

__all__ = ["BrightnessDial", "BrightnessDials"]


class BrightnessDial(Protocol):
    """What the switch asks of a brightness number entity."""

    @property
    def dialled_in_value(self) -> int | None: ...
    @property
    def native_value(self) -> int: ...
    def set_dialled_in(self, value: int) -> None: ...
    def reset(self, *, apply: bool = True) -> None: ...


class BrightnessDials:
    """The night and the day dial of one instance."""

    def __init__(self, get_entity: Callable[[str], object | None]) -> None:
        """Initialize the dials.

        Args:
            get_entity: Finds another entity of the instance by key; the
                dials do not exist before their platform has been set up
        """
        self._get_entity = get_entity

    def night(self) -> BrightnessDial | None:
        """The night dial, None before it is set up."""
        return self._get_entity(KEY_NIGHT_BRIGHTNESS)  # type: ignore[return-value]

    def day(self) -> BrightnessDial | None:
        """The day dial, None before it is set up."""
        return self._get_entity(KEY_DAY_BRIGHTNESS)  # type: ignore[return-value]

    def dialled_in_night(self) -> int | None:
        """Dialled-in night brightness, None when nobody has dialled one in."""
        dial = self.night()
        return None if dial is None else dial.dialled_in_value

    def dialled_in_day(self) -> int | None:
        """Dialled-in day brightness, None when nobody has dialled one in."""
        dial = self.day()
        return None if dial is None else dial.dialled_in_value

    def reset_all(self, *, apply: bool = True) -> None:
        """Drop both dialled-in values, back to the configured ones."""
        for dial in (self.night(), self.day()):
            if dial is not None:
                dial.reset(apply=apply)

    def reset_for_mode(self, mode: str, *, apply: bool = True) -> None:
        """Drop the dialled-in value that belongs to *mode*, if it has one.

        A dim press never reaches the other phase's dial, and leaving it alone
        avoids clearing a value that still belongs to another part of the day.
        """
        dial = {MODE_NIGHT: self.night, MODE_DAY: self.day}.get(mode)
        if dial is None:
            return
        entity = dial()
        if entity is not None:
            entity.reset(apply=apply)
