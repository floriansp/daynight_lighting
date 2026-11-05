"""Transition coordinator for DayNight Lighting.

This module coordinates transitions between modes, extracting the transition
handlers from the main switch into a dedicated coordinator class.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from homeassistant.components.light import ATTR_BRIGHTNESS_PCT, ATTR_COLOR_TEMP_KELVIN

from .const import (
    MODE_DAY,
    MODE_NIGHT,
    MODE_WAKEUP,
)
from .light_applier import LightApplier

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from .lights import LightsController
    from .handlers import ModeHandler
    from .manual_control import ExpectedState
    from .motion import MotionController
    from .state_controller import StateController

_LOGGER = logging.getLogger(__name__)

__all__ = ["TransitionCoordinator"]


class TransitionCoordinator:
    """Coordinates transitions between modes."""

    def __init__(
        self,
        hass: HomeAssistant,
        instance_name: str,
        handlers: dict[str, ModeHandler],
        lights: LightsController,
        motion: MotionController,
        state_ctrl: StateController,
        get_transition: Callable[[str], int],
        is_control_brightness_on: Callable[[], bool],
        is_control_color_on: Callable[[], bool],
        on_applied: Callable[[ExpectedState], None] | None = None,
        mark_applied: Callable[[list[str]], None] | None = None,
    ) -> None:
        """Initialize transition coordinator.

        Args:
            hass: Home Assistant instance
            instance_name: Instance name for logging
            handlers: Dictionary of mode handlers (MODE_DAY, MODE_NIGHT, etc.)
            lights: Lights controller
            motion: Motion controller
            state_ctrl: State controller
            get_transition: Callable to get transition duration
            is_control_brightness_on: Callable to check brightness control
            is_control_color_on: Callable to check color control
            on_applied: Observer notified with the values we command
            mark_applied: Observer notified with the lights we command, to
                exempt them from detection while the command is in flight
        """
        self._hass = hass
        self._instance_name = instance_name
        self._handlers = handlers
        self._lights = lights
        self._motion = motion
        self._state_ctrl = state_ctrl
        self._get_transition = get_transition
        self._is_control_brightness_on = is_control_brightness_on
        self._is_control_color_on = is_control_color_on
        self._applier = LightApplier(
            hass,
            state_ctrl,
            get_transition,
            instance_name,
            on_applied=on_applied,
            mark_applied=mark_applied,
        )

    def transition_sync(self, from_mode: str, to_mode: str) -> None:
        """Execute transition between modes (synchronous).

        This synchronous version avoids race conditions with tick().

        Args:
            from_mode: The mode we're leaving
            to_mode: The mode we're entering
        """
        transition_key = f"{from_mode}→{to_mode}"

        _LOGGER.debug(
            "[%s] Mode transition: %s",
            self._instance_name,
            transition_key,
        )

        # Call exit on old handler if it exists
        if from_mode in self._handlers:
            self._handlers[from_mode].exit(to_mode)

        # Call enter on new handler if it exists
        if to_mode in self._handlers:
            self._handlers[to_mode].enter(from_mode)

        # A wake-up that ends hands the room to the next mode, and that mode's
        # values were never applied by its own tick yet.
        if from_mode == MODE_WAKEUP and to_mode in (MODE_DAY, MODE_NIGHT):
            self._apply_mode_expected_state(to_mode)

    def _turn_off_lights(self, lights: list[str]) -> None:
        """Turn off lights with transition."""
        self._applier.turn_off(lights, transition="mode")

    def _apply_mode_expected_state(self, mode: str) -> None:
        """Apply the expected state from a mode handler.

        Used after wake-up/sleep modes complete to ensure the target mode's
        expected state is applied (e.g., turn off if day mode fallback is OFF).

        Args:
            mode: The target mode (MODE_DAY or MODE_NIGHT)
        """
        if mode not in self._handlers:
            return

        handler = self._handlers[mode]
        lights = self._lights.get_lights_list()
        if not lights:
            return

        # Get expected state from handler
        expected = handler.calculate_expected_state()

        if not expected.on:
            # Mode expects lights OFF - turn them off
            _LOGGER.debug(
                "[%s] %s expects lights OFF after transition, turning off",
                self._instance_name,
                mode,
            )
            self._turn_off_lights(lights)
        else:
            # Mode expects lights ON - apply the mode's values
            _LOGGER.debug(
                "[%s] %s expects lights ON after transition (brightness=%s, kelvin=%s)",
                self._instance_name,
                mode,
                expected.brightness_pct,
                expected.kelvin,
            )
            # Build payload based on expected state
            payload: dict[str, Any] = {"entity_id": lights}

            if self._is_control_brightness_on() and expected.brightness_pct is not None:
                payload[ATTR_BRIGHTNESS_PCT] = expected.brightness_pct

            if self._is_control_color_on() and expected.kelvin is not None:
                payload[ATTR_COLOR_TEMP_KELVIN] = expected.kelvin

            if len(payload) > 1:
                self._applier.turn_on(
                    lights,
                    payload,
                    transition="mode",
                    brightness_pct=expected.brightness_pct if self._is_control_brightness_on() else None,
                    kelvin=expected.kelvin if self._is_control_color_on() else None,
                )
