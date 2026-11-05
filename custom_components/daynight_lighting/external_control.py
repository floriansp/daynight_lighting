"""Event-driven detection of external control on a single light.

Whenever a configured light reports a state, the report is compared with the
expected state we recorded when we last commanded that light. A deviation is a
foreign intervention (a scene, a wall dimmer, another automation) and is
written into the holds, so the day/night automation leaves the light alone.

Inside a sleep or wake-up ramp the rule is different: the ramp moves
brightness and colour legitimately, so only an external OFF counts, and it ends
the whole ramp instead of creating a hold.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Callable

from .state_controller import HOLD_REASON_DETECTED

if TYPE_CHECKING:
    from .hold_validation import RestoredHoldValidator
    from .manual_control import DetectionPolicy, ManualControlDetector
    from .state_controller import StateController

    from homeassistant.core import HomeAssistant

__all__ = ["ExternalControlMonitor"]

_LOGGER = logging.getLogger(__name__)


class ExternalControlMonitor:
    """Judges one reported light state against what we expect of that light."""

    def __init__(
        self,
        hass: HomeAssistant,
        state_ctrl: StateController,
        detector: ManualControlDetector,
        restored_holds: RestoredHoldValidator,
        detection_policy: Callable[[], DetectionPolicy],
        in_ramp: Callable[[], bool],
        interrupt_ramp: Callable[[], None],
        is_startup_guard_active: Callable[[], bool],
        instance_name: str = "",
    ) -> None:
        """Initialize the monitor.

        Args:
            hass: Home Assistant instance
            state_ctrl: Holds and expected states
            detector: Compares a light's state to its expected state
            restored_holds: Judges a restored hold the moment its lamp reports
            detection_policy: The ruler a light is judged with right now, the
                same one the restored-hold re-validation uses
            in_ramp: True while a sleep or wake-up ramp moves the values
            interrupt_ramp: Ends the running ramp and jumps into its block
            is_startup_guard_active: True until the mode handlers have applied
                once, so their first commands are not read as intervention
            instance_name: Instance name for logging
        """
        self._hass = hass
        self._state_ctrl = state_ctrl
        self._detector = detector
        self._restored_holds = restored_holds
        self._detection_policy = detection_policy
        self._in_ramp = in_ramp
        self._interrupt_ramp = interrupt_ramp
        self._is_startup_guard_active = is_startup_guard_active
        self._instance_name = instance_name

    def handle_state_report(self, entity_id: str) -> None:
        """Judge *entity_id* after it reported a state."""
        # A restored hold whose light had not reported yet is judged the
        # moment the lamp does — before the startup/grace guards below,
        # which have nothing to do with that decision.
        if self._restored_holds.is_pending(entity_id):
            self._restored_holds.revalidate_pending([entity_id])

        # Mode handlers have not applied yet after startup.
        if self._is_startup_guard_active():
            return

        # Our own command is still in flight.
        if self._detector.is_in_grace_period(entity_id):
            return

        # We have not applied values to this light, so there is nothing to
        # compare against.
        if self._state_ctrl.get_expected_state(entity_id) is None:
            return

        policy = self._detection_policy()
        external_lights = self._detector.check_external_control(
            self._hass,
            [entity_id],
            self._state_ctrl,
            check_brightness=policy.check_brightness,
            check_color=policy.check_color,
            brightness_tolerance_pct=policy.brightness_tolerance_pct,
            kelvin_tolerance=policy.kelvin_tolerance,
        )
        if not external_lights:
            return

        _LOGGER.info(
            "[%s] External control detected on %s (event-driven)",
            self._instance_name,
            entity_id,
        )

        if self._in_ramp():
            # "Ich bin müde, ich will aus": an external OFF ends the whole
            # ramp and jumps into the block, exactly like the wall-button
            # turn_off with hold.
            self._interrupt_ramp()
            return

        self._state_ctrl.set_hold(external_lights, reason=HOLD_REASON_DETECTED)
