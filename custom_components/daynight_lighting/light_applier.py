"""Single entry point for switching the lights of an instance.

Switching lights always involves three steps: the service call, the
bookkeeping of which lights we control, and the expected state that external
control detection compares against. A caller that performs the service call
but forgets the expected state makes the integration report its own change as
external control, which switches the instance to manual control.

Routing every internal turn-on and turn-off through :class:`LightApplier`
keeps the three steps together.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Callable

from .manual_control import ExpectedState

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from .state_controller import StateController

_LOGGER = logging.getLogger(__name__)


class LightApplier:
    """Applies light changes and keeps the tracked state in sync."""

    def __init__(
        self,
        hass: HomeAssistant,
        state_ctrl: StateController,
        get_transition: Callable[[str], int],
        instance_name: str = "",
        on_applied: Callable[[ExpectedState], None] | None = None,
        mark_applied: Callable[[list[str]], None] | None = None,
    ) -> None:
        """Initialize the applier.

        Args:
            hass: Home Assistant instance
            state_ctrl: State controller holding controlled and expected state
            get_transition: Callable resolving a transition context to seconds
            instance_name: Instance name for logging
            on_applied: Observer notified with the values we just commanded
            mark_applied: Observer notified with the lights we just commanded,
                so external-control detection exempts them while the command
                is in flight (grace period).
        """
        self._hass = hass
        self._state_ctrl = state_ctrl
        self._get_transition = get_transition
        self._instance_name = instance_name
        self._on_applied = on_applied
        self._mark_applied = mark_applied

    def turn_on(
        self,
        lights: list[str],
        payload: dict[str, Any],
        *,
        transition: str,
        brightness_pct: int | None = None,
        kelvin: int | None = None,
    ) -> None:
        """Turn lights on, mark them controlled and record expected values.

        Args:
            lights: Lights to mark as controlled
            payload: Prebuilt ``light.turn_on`` payload (including entity_id)
            transition: Transition context ("tick", "initial" or "mode")
            brightness_pct: Expected brightness, None if we don't control it
            kelvin: Expected color temperature, None if we don't control it
        """
        self._call("turn_on", self._with_transition(payload, transition))
        self._state_ctrl.mark_controlled(lights)
        for lid in lights:
            self._state_ctrl.set_expected_state(
                lid,
                on=True,
                brightness_pct=brightness_pct,
                kelvin=kelvin,
            )
        self._notify(
            ExpectedState(on=True, brightness_pct=brightness_pct, kelvin=kelvin)
        )
        self._mark_applied_now(lights)

    def turn_off(self, lights: list[str], *, transition: str) -> None:
        """Turn lights off, release them and record expected state as OFF.

        Args:
            lights: Lights to turn off
            transition: Transition context ("tick", "initial" or "mode")
        """
        payload: dict[str, Any] = {"entity_id": lights}
        self._call("turn_off", self._with_transition(payload, transition))
        self._state_ctrl.unmark_controlled(lights)
        for lid in lights:
            self._state_ctrl.set_expected_state(lid, on=False)
        self._notify(ExpectedState(on=False))
        self._mark_applied_now(lights)

    def _notify(self, applied: ExpectedState) -> None:
        """Report what we commanded; observers must never break switching."""
        if self._on_applied is None:
            return
        try:
            self._on_applied(applied)
        except Exception:  # noqa: BLE001 - monitoring must not affect control
            _LOGGER.exception("Applied-state observer raised, ignoring")

    def _mark_applied_now(self, lights: list[str]) -> None:
        """Exempt the commanded lights from detection while in flight."""
        if self._mark_applied is None:
            return
        try:
            self._mark_applied(lights)
        except Exception:  # noqa: BLE001 - detection must not affect switching
            _LOGGER.exception("mark-applied observer raised, ignoring")

    def _with_transition(
        self, payload: dict[str, Any], transition: str
    ) -> dict[str, Any]:
        """Add the transition key to the payload if the context yields one."""
        seconds = self._get_transition(transition)
        if seconds > 0:
            payload["transition"] = seconds
        return payload

    def _call(self, service: str, payload: dict[str, Any]) -> None:
        """Fire the light service without awaiting it."""
        self._hass.async_create_task(
            self._hass.services.async_call("light", service, payload)
        )
