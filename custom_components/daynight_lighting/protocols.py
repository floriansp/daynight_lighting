"""Protocol definitions for DayNight Lighting.

This module defines the interfaces between the main switch and its
collaborators, enabling dependency inversion and testability.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

__all__ = [
    "ColorProvider",
    "ModeProvider",
]


@runtime_checkable
class ColorProvider(Protocol):
    """Protocol for components that provide color temperature."""

    def is_enabled(self) -> bool:
        """Return True if color control is enabled."""
        ...

    def get_kelvin(self) -> tuple[int, float | None]:
        """Return color temperature in Kelvin and optional metadata.

        Returns:
            Tuple of (kelvin, metadata). Metadata may be sun elevation
            or None depending on implementation.
        """
        ...

    def get_expected_night_kelvin(self) -> int | None:
        """Return color temperature for night mode, or None if disabled."""
        ...


@runtime_checkable
class ModeProvider(Protocol):
    """Protocol for mode determination."""

    def get_current_mode(self) -> str:
        """Return current mode identifier.

        Returns:
            One of: MODE_DAY, MODE_NIGHT, MODE_SLEEP, MODE_WAKEUP
        """
        ...

    def is_day_mode(self) -> bool:
        """Check if currently in day mode (LUX-based control).

        Returns True for day mode, False for night mode.
        Note: sleep and wake-up modes are handled separately via
        get_current_mode().
        """
        ...
