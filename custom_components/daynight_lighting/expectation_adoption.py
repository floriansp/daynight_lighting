"""Adopting what an uncommanded light actually shows.

A hold release can end without commanding every light it freed (a service
ramp owns them, or the off timer selected nothing). The expectation recorded
before the hold then still describes the scene's values, and the next state
report reads as a fresh intervention — the hold is back within minutes,
locking the integration out of the room it just reclaimed.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Callable

from homeassistant.const import STATE_ON, STATE_UNAVAILABLE, STATE_UNKNOWN

from .domain.brightness import brightness_to_pct
from .manual_control import reported_kelvin

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from .state_controller import StateController

__all__ = ["ExpectationAdopter"]

_LOGGER = logging.getLogger(__name__)


class ExpectationAdopter:
    """Brings the recorded expectation of a light up to date with reality."""

    def __init__(
        self,
        hass: HomeAssistant,
        state_ctrl: StateController,
        mark_applied: Callable[[list[str]], None],
        instance_name: str = "",
    ) -> None:
        """Initialize the adopter.

        Args:
            hass: Home Assistant instance
            state_ctrl: Where the expectations are recorded
            mark_applied: Exempts lights from detection for the grace period,
                so our own adoption is never read as a change we did not make
            instance_name: Instance name for logging
        """
        self._hass = hass
        self._state_ctrl = state_ctrl
        self._mark_applied = mark_applied
        self._instance_name = instance_name

    def adopt(self, released: list[str], commanded: list[str]) -> list[str]:
        """Record what each released but uncommanded light actually shows.

        Adoption is the honest statement "this is how the light looks and we
        did not command it": it claims no ownership, touches no light list and
        creates no hold. It only keeps the expectation from being older than
        the release. Returns the lights it adopted.
        """
        commanded_set = set(commanded)
        adopted: list[str] = []
        for lid in released:
            if lid in commanded_set:
                continue
            state = self._hass.states.get(lid)
            if state is None or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
                # Nothing truthful to record; the next real report is judged
                # against whatever is there, which is the lesser evil.
                continue
            on = state.state == STATE_ON
            attrs = getattr(state, "attributes", {}) or {}
            brightness = brightness_to_pct(attrs.get("brightness")) if on else None
            self._state_ctrl.set_expected_state(
                lid,
                on=on,
                brightness_pct=brightness,
                kelvin=reported_kelvin(attrs) if on else None,
            )
            self._mark_applied([lid])
            _LOGGER.debug(
                "[%s] %s: adopted current state after release (nothing was commanded)",
                self._instance_name,
                lid,
            )
            adopted.append(lid)
        return adopted
