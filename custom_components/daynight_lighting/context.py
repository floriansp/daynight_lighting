"""Shared context for mode handlers.

This module defines dataclasses that group common dependencies passed to
mode handlers, reducing parameter sprawl and making the codebase more
maintainable.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable

from .light_applier import LightApplier
from .manual_control import ExpectedState

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from .lights import LightsController
    from .state_controller import StateController


@dataclass(frozen=True)
class SharedHandlerDeps:
    """Shared dependencies passed to all mode handlers.

    This dataclass groups the common dependencies that every mode handler
    needs, reducing constructor parameter count and making it easier to add
    new shared dependencies.

    Attributes:
        hass: Home Assistant instance
        instance_name: Name of this DayNight instance for logging
        lights: Controller for light operations
        state_ctrl: Controller for persistent state management
        is_control_brightness_on: Callable returning True if brightness control is enabled
        is_control_color_on: Callable returning True if color control is enabled
        get_transition: Callable to get transition duration for a given context
        on_applied: Observer notified with the values we command
        get_night_brightness: Callable returning the dialled-in night
            brightness, None to fall back to the configured value
        get_day_brightness: Callable returning the dialled-in day brightness
            (fixed fallback), None to fall back to the configured value
        get_held_lights: Callable returning the set of lights a service holds
            in place until the phase ends
        is_safety_room_on: Callable returning True while the safety room
            (force defaults) switch is on — then nothing is excluded and the
            handlers enforce defaults even on held lights
    """

    hass: HomeAssistant
    instance_name: str
    lights: LightsController
    state_ctrl: StateController
    is_control_brightness_on: Callable[[], bool]
    is_control_color_on: Callable[[], bool]
    get_transition: Callable[[str], int]
    on_applied: Callable[[ExpectedState], None] | None = None
    mark_applied: Callable[[list[str]], None] | None = None
    is_in_grace_period: Callable[[str], bool] = lambda _: False
    get_night_brightness: Callable[[], int | None] = lambda: None
    get_day_brightness: Callable[[], int | None] = lambda: None
    get_held_lights: Callable[[], set[str]] = lambda: set()
    is_safety_room_on: Callable[[], bool] = lambda: False

    def exclude_held(self, lights: list[str]) -> list[str]:
        """Drop lights a service holds in place until the phase ends.

        The mode handlers call this before applying, so a visitor's
        ``turn_on``/``turn_off`` is not undone by the day/night automation.
        In a safety room the hold is ignored: the handlers get the full list
        and enforce the defaults even during the phase.
        """
        if self.is_safety_room_on():
            return lights
        held = self.get_held_lights()
        if not held:
            return lights
        return [lid for lid in lights if lid not in held]

    def all_held(self, lights: list[str]) -> bool:
        """True when every light in *lights* is excluded (held).

        Shortcut for logging; the actual filtering is done by
        :meth:`exclude_held`.
        """
        return bool(lights) and not self.exclude_held(lights)

    @property
    def light_applier(self) -> LightApplier:
        """Applier that switches lights and keeps the tracked state in sync."""
        return LightApplier(
            self.hass,
            self.state_ctrl,
            self.get_transition,
            self.instance_name,
            on_applied=self.on_applied,
            mark_applied=self.mark_applied,
        )


@dataclass(frozen=True)
class ControlContext:
    """Context for control operations.

    Groups the core context needed for creating components and controllers.

    Attributes:
        hass: Home Assistant instance
        config_entry_id: Configuration entry ID for state storage
        instance_name: Name of this DayNight instance
    """

    hass: HomeAssistant
    config_entry_id: str
    instance_name: str
