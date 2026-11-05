"""Re-validation of detected holds that were restored from storage.

A ``detected`` hold survives a restart and a phase change and ends only
through an explicit release, so after a restart it may keep the integration
off a light whose intervention is long gone. This module judges such holds
against what their light shows now.

The decision itself (:func:`hold_release_reason`) is one pure function, shared
by the load-time check and by the deferred check of a lamp that had not
reported yet, so a light is never judged by two different rules.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Callable

from homeassistant.const import STATE_ON, STATE_UNAVAILABLE, STATE_UNKNOWN

from .manual_control import DetectionPolicy, compare_light_to_target
from .state_controller import HOLD_REASON_DETECTED

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from .state_controller import ExpectedRecord, StateController

__all__ = ["RestoredHoldValidator", "hold_release_reason"]

_LOGGER = logging.getLogger(__name__)


def hold_release_reason(
    state: Any,
    expected: ExpectedRecord | None,
    policy: DetectionPolicy,
) -> str | None:
    """Why a detected hold no longer protects *state*, or None to keep it.

    The caller passes a real (on or off) state; an unusable state is the
    caller's business, because "no evidence yet" means something different on
    each path.

    The hold stays as long as the light still differs from what we expected:
    an off light we wanted on is the user keeping the room dark, and any
    brightness/colour outside tolerance is an intervention. Only a light that
    is where we left it has nothing left to protect.
    """
    if expected is None:
        return "no expected state"

    actual_on = state.state == STATE_ON
    if expected.get("on", False) != actual_on:
        return None
    if not actual_on:
        return "matched expected state"

    comparison = compare_light_to_target(
        getattr(state, "attributes", {}) or {},
        expected.get("brightness_pct"),
        expected.get("kelvin"),
        brightness_tolerance_pct=policy.brightness_tolerance_pct,
        kelvin_tolerance=policy.kelvin_tolerance,
        check_brightness=policy.check_brightness,
        check_color=policy.check_color,
    )
    if comparison.brightness_differs or comparison.color_differs:
        return None
    return "matched expected state"


class RestoredHoldValidator:
    """Judges restored detected holds, now or once their lamp reports."""

    def __init__(
        self,
        hass: HomeAssistant,
        state_ctrl: StateController,
        detection_policy: Callable[[], DetectionPolicy],
        instance_name: str = "",
    ) -> None:
        """Initialize the validator.

        Args:
            hass: Home Assistant instance
            state_ctrl: Holds and expected states
            detection_policy: Resolves the ruler a light is judged with right
                now, so this check and the live detection never disagree
            instance_name: Instance name for logging
        """
        self._hass = hass
        self._state_ctrl = state_ctrl
        self._detection_policy = detection_policy
        self._instance_name = instance_name
        # Restored detected holds whose light had not reported yet, mapped to
        # the expected state as it was at load.
        self._pending: dict[str, ExpectedRecord | None] = {}

    @property
    def has_pending(self) -> bool:
        """True while a restored hold waits for its lamp to report."""
        return bool(self._pending)

    def is_pending(self, light_id: str) -> bool:
        """True if the hold of *light_id* still waits for its lamp to report."""
        return light_id in self._pending

    def revalidate_restored(self) -> None:
        """Judge the detected holds that were restored from storage.

        Called from both load paths right after ``prune`` and before
        ``mark_applied``: only holds whose light already matches are released,
        so the grace period that follows cannot turn a release into a false
        detection.

        A lamp that has not reported yet cannot be judged, so its hold is kept
        and handed to :meth:`revalidate_pending`. A lamp that reports
        *unavailable* is different: the device is there and says it cannot
        tell us anything, which is no evidence that the hold is still needed.
        """
        detected = [
            lid
            for lid, reason in self._state_ctrl.get_held_lights_with_reasons().items()
            if reason == HOLD_REASON_DETECTED
        ]
        self._pending.clear()
        if not detected:
            return

        policy = self._detection_policy()
        stale: list[str] = []
        for lid in detected:
            state = self._hass.states.get(lid)
            if state is None:
                # Judge it when the lamp reports; see revalidate_pending.
                # Copied, not referenced: the snapshot must not follow a later
                # change to the live record (see _snapshot_expected).
                self._pending[lid] = self._snapshot_expected(lid)
                continue
            if state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
                reason = "unavailable"
            else:
                reason = hold_release_reason(
                    state, self._state_ctrl.get_expected_state(lid), policy
                )
                if reason is None:
                    continue
            self._log_released(lid, reason)
            stale.append(lid)

        if stale:
            self._state_ctrl.release_hold(stale)

    def revalidate_pending(self, lights: list[str] | None = None) -> None:
        """Judge a deferred hold the moment its lamp reports.

        At startup the switch is added before the lights report, so the hold
        of a lamp that was still silent had to be deferred. It is judged
        against the expected state *snapshotted at load*, not the live record:
        the first tick rewrites that one before the lamps are back.

        Called with the reporting *lights* from the state-change listener, and
        without arguments from the first tick to also cover a report that
        arrived between the load-time check and the subscription. An
        ``unavailable``/``unknown`` report is no evidence either way, so the
        hold keeps waiting — the light is uncontrollable meanwhile.
        """
        self._forget_released()
        if lights is None:
            lights = list(self._pending)
        else:
            lights = [lid for lid in lights if lid in self._pending]
        if not lights:
            return

        policy = self._detection_policy()
        stale: list[str] = []
        for lid in lights:
            state = self._hass.states.get(lid)
            if state is None or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
                continue
            # Popped before the decision: a real report validates the hold once,
            # whether it survives or not.
            reason = hold_release_reason(state, self._pending.pop(lid), policy)
            if reason is None:
                continue
            self._log_released(lid, reason)
            stale.append(lid)

        if stale:
            self._state_ctrl.release_hold(stale)

    def _forget_released(self) -> None:
        """Drop pending entries whose hold ended while the lamp was silent."""
        held = self._state_ctrl.get_held_lights_with_reasons()
        self._pending = {
            lid: expected
            for lid, expected in self._pending.items()
            if held.get(lid) == HOLD_REASON_DETECTED
        }

    def _snapshot_expected(self, light_id: str) -> ExpectedRecord | None:
        """The expected state as it is right now, detached from the live record.

        ``StateController.get_expected_state`` hands out its stored dict, so
        keeping it would make the deferred check follow whatever the next tick
        writes. Copying keeps the value the light is judged against the one
        that was in effect when the hold was restored.
        """
        expected = self._state_ctrl.get_expected_state(light_id)
        return expected.copy() if expected is not None else None

    def _log_released(self, light_id: str, reason: str) -> None:
        """Log one released hold, one line per light."""
        _LOGGER.info(
            "[%s] Restored hold released for %s: %s",
            self._instance_name,
            light_id,
            reason,
        )
