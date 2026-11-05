"""Base protocol and utilities for mode handlers.

This module defines the ModeHandler protocol that all mode-specific handlers
implement, along with shared utility functions.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from ..domain.brightness import brightness_to_pct, lux_to_brightness_pct
from ..manual_control import ExpectedState

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from ..context import SharedHandlerDeps
    from ..lights import LightsController
    from ..state_controller import StateController

__all__ = [
    "BaseModeHandler",
    "ModeHandler",
    "brightness_to_pct",
    "lux_to_brightness_pct",
]


class BaseModeHandler:
    """Shared plumbing of the mode handlers.

    Holds the shared dependencies and exposes them under short names, so the
    four handlers do not each repeat the same accessors. Behaviour stays in
    the handlers; this class only forwards.
    """

    def __init__(self, shared: SharedHandlerDeps) -> None:
        """Keep the shared dependencies (hass, instance_name, lights, etc.)."""
        self._shared = shared

    @property
    def _hass(self) -> HomeAssistant:
        return self._shared.hass

    @property
    def _instance_name(self) -> str:
        return self._shared.instance_name

    @property
    def _lights(self) -> LightsController:
        return self._shared.lights

    @property
    def _state_ctrl(self) -> StateController:
        return self._shared.state_ctrl

    @property
    def _is_control_brightness_on(self) -> Callable[[], bool]:
        return self._shared.is_control_brightness_on

    @property
    def _is_control_color_on(self) -> Callable[[], bool]:
        return self._shared.is_control_color_on

    @property
    def _get_transition(self) -> Callable[[str], int]:
        return self._shared.get_transition

    def _turn_off_lights(self, lights: list[str]) -> None:
        """Turn off lights with transition."""
        self._shared.light_applier.turn_off(lights, transition="tick")


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

