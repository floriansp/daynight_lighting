"""Base protocol and utilities for mode handlers.

This module defines the ModeHandler protocol that all mode-specific handlers
implement, along with shared utility functions.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from ..domain.brightness import brightness_to_pct, lux_to_brightness_pct
from ..manual_control import ExpectedState

__all__ = ["ModeHandler", "brightness_to_pct", "lux_to_brightness_pct"]


@runtime_checkable
class ModeHandler(Protocol):
    """Protocol for mode-specific behavior handlers."""

    def tick(self) -> None:
        """Execute periodic logic for this mode."""
        ...

    def enter(self, previous_mode: str | None) -> None:
        """Called when entering this mode."""
        ...

    def exit(self, next_mode: str) -> None:
        """Called when exiting this mode."""
        ...

    def forget_applied_values(self) -> None:
        """Drop what this mode remembers having commanded.

        Called when a manual episode ends. Anything a mode remembers about
        its own commands describes the lights only as long as nobody else
        touched them, and damping a new command against a stale memory is
        how a room gets stuck at somebody else's brightness.
        """
        ...

    def get_brightness_pct(self) -> int | None:
        """Calculate brightness for current state."""
        ...

    def build_light_payload(self, lights: list[str]) -> dict[str, Any] | None:
        """Build service call payload for lights."""
        ...

    def calculate_expected_state(self) -> ExpectedState:
        """Calculate expected light state based on current conditions.

        Returns the state we expect lights to be in based on:
        - Current sensor readings (LUX, motion)
        - Time-based calculations (sleep/wake progress)
        - Configuration (fallbacks, brightness settings)

        This is used for external control detection.
        """
        ...

