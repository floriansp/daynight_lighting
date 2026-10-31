"""Night mode handler for DayNight Lighting.

Handles night mode: motion-based on/off with fixed brightness.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Callable

from homeassistant.components.light import ATTR_BRIGHTNESS_PCT, ATTR_COLOR_TEMP_KELVIN
from homeassistant.const import STATE_ON

from ..config import NightModeConfig
from ..const import (
    NIGHT_FALLBACK_KEEP,
    NIGHT_FALLBACK_OFF,
    NIGHT_FALLBACK_ON,
    NIGHT_FALLBACK_SKIP,
)
from ..context import SharedHandlerDeps
from ..manual_control import (
    NIGHT_BRIGHTNESS_TOLERANCE,
    NIGHT_KELVIN_TOLERANCE,
    TIGHT_BRIGHTNESS_TOLERANCE_PCT,
    TIGHT_KELVIN_TOLERANCE,
    ExpectedState,
    compare_light_to_target,
)
from ..protocols import ColorProvider
from ..state_controller import HOLD_REASON_DETECTED

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from ..action_scheduler import ActionScheduler
    from ..motion import MotionController

__all__ = ["NightModeHandler"]

_LOGGER = logging.getLogger(__name__)


class NightModeHandler:
    """Handles night mode: motion-based on/off, fixed brightness."""

    def __init__(
        self,
        shared: SharedHandlerDeps,
        config: NightModeConfig,
        motion: MotionController,
        action_scheduler: ActionScheduler,
        circadian: ColorProvider,
    ) -> None:
        """Initialize night mode handler.

        Args:
            shared: Shared dependencies (hass, instance_name, lights, etc.)
            config: Night mode configuration
            motion: Motion controller for detecting motion
            action_scheduler: Scheduler for delayed actions
            circadian: Color provider for night color temperature
        """
        self._shared = shared
        self._config = config
        self._motion = motion
        self._action_scheduler = action_scheduler
        self._circadian = circadian
        # True while the lights still carry values from the previous mode
        # right after entering night (a "leave" transition, or a "turn_off"
        # transition that skipped the off because presence was already
        # active). The first motion event must re-apply the night target
        # instead of holding the lights as an external scene (see
        # _apply_motion_on).
        self._reapply_instead_of_hold = False

    # Convenience properties for shared dependencies
    @property
    def _hass(self) -> HomeAssistant:
        return self._shared.hass

    @property
    def _instance_name(self) -> str:
        return self._shared.instance_name

    @property
    def _lights(self):
        return self._shared.lights

    @property
    def _state_ctrl(self):
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

    def tick(self) -> None:
        """Night-mode per-minute tick.

        External control is detected event-driven by the main switch and
        written into ``held_lights``; the per-light filtering happens in the
        fallback via ``exclude_held``.
        """
        lights = self._lights.get_lights_list()

        # Check if motion sensor is configured
        if not self._motion.get_motion_sensor_entity():
            self._apply_night_mode_fallback(lights)
            return

        # When motion sensor is configured, we only apply night mode on motion
        # The central tick handles external control detection

    def enter(self, previous_mode: str | None) -> None:
        """Called when entering night mode."""
        on_enter = self._config.on_enter_night

        # Skip turn_off if fallback will immediately turn lights back on
        fallback_will_turn_on = (
            not self._motion.get_motion_sensor_entity()
            and self._config.fallback == NIGHT_FALLBACK_ON
        )

        motion_now = self._motion.has_motion_now()

        if on_enter == "turn_off" and not fallback_will_turn_on:
            if motion_now:
                # Presence is already active: switching the lights off and
                # straight back on would flicker. Re-apply the night target
                # to the lights that are already on instead, exactly like the
                # "leave" path; the off-timer still turns them off once the
                # room empties.
                self._reapply_instead_of_hold = True
            else:
                # A visitor's held choice must survive, so only the non-held
                # lights are switched off here.
                lights = self._shared.exclude_held(self._lights.get_lights_list())
                if lights:
                    _LOGGER.debug(
                        "[%s] Day->Night: turning lights off",
                        self._instance_name,
                    )
                    self._turn_off_lights(lights)
        else:
            # The lights keep their day values through the transition. The
            # first motion event must bring them to the night target rather
            # than holding them as "externally diverged" (a scene that is
            # not there).
            self._reapply_instead_of_hold = True

        # If motion is already active, apply night mode now
        if motion_now:
            _LOGGER.debug(
                "[%s] Day->Night: motion already active, applying night mode",
                self._instance_name,
            )
            self.handle_motion_on()

    def forget_applied_values(self) -> None:
        """Nothing to forget: night mode aims at a value, it remembers none."""

    def exit(self, next_mode: str) -> None:
        """Called when exiting night mode."""
        self._cancel_off_timer()

    def calculate_expected_state(self) -> ExpectedState:
        """Calculate expected light state based on current conditions.

        For night mode:
        - Without motion sensor: based on fallback setting
        - With motion sensor: ON if motion detected, OFF otherwise
        - Brightness is fixed night brightness
        - Color is circadian night color (if enabled)
        """
        # Check if motion sensor is configured
        if not self._motion.get_motion_sensor_entity():
            # No motion sensor - use fallback behavior
            fallback = self._config.fallback

            if fallback == NIGHT_FALLBACK_ON:
                on = True
            elif fallback == NIGHT_FALLBACK_OFF:
                return ExpectedState(on=False)
            else:  # SKIP or KEEP
                return ExpectedState(on=False)
        else:
            # Motion sensor - on if motion detected
            on = self._motion.has_motion_now()

        if not on:
            return ExpectedState(on=False)

        # Calculate expected brightness
        brightness_pct = None
        if self._is_control_brightness_on():
            brightness_pct = self._target_brightness()

        # Calculate expected color
        kelvin = None
        if self._is_control_color_on() and self._circadian.is_enabled():
            kelvin = self._circadian.get_expected_night_kelvin()

        _LOGGER.debug(
            "[%s] NightModeHandler.calculate_expected_state: on=%s, brightness=%s, config.brightness=%s",
            self._instance_name,
            on,
            brightness_pct,
            self._config.brightness,
        )

        return ExpectedState(
            on=True,
            brightness_pct=brightness_pct,
            kelvin=kelvin,
        )

    def get_brightness_pct(self) -> int:
        """Return the night brightness currently in effect."""
        return self._target_brightness()

    def _target_brightness(self) -> int:
        """Night brightness in effect: the dialled-in value, else the config.

        Single point of access for every night-mode path, so that a dimmed
        room stays dimmed consistently — including the comparison in
        :meth:`_light_matches_night_values`, which otherwise aborts the
        motion turn-on logic for a light that no longer matches the config.
        """
        dialled_in = self._shared.get_night_brightness()
        if dialled_in is None:
            return self._config.brightness
        return dialled_in

    def build_light_payload(self, lights: list[str]) -> dict[str, Any]:
        """Build light.turn_on payload for night mode."""
        payload: dict[str, Any] = {"entity_id": lights}
        if self._is_control_brightness_on():
            payload[ATTR_BRIGHTNESS_PCT] = self._target_brightness()
        if self._is_control_color_on() and self._circadian.is_enabled():
            kelvin = self._circadian.get_expected_night_kelvin()
            if kelvin is not None:
                payload[ATTR_COLOR_TEMP_KELVIN] = kelvin
                _LOGGER.debug(
                    "[%s] Night: circadian %dK",
                    self._instance_name,
                    kelvin,
                )
        return payload

    def handle_motion_on(self) -> None:
        """Night mode: motion/presence detected -> turn on lights."""
        self._apply_motion_on(reapply_diverged=False)

    def reapply_after_release(self) -> None:
        """Take the lights back to the night target after a hold release.

        A just-released light still shows the (now overridden) scene's values,
        so :meth:`handle_motion_on` would treat it as a fresh divergence and
        re-hold it on the spot. Re-applying instead makes the release button
        actually reclaim the room. The off-timer still decides whether the
        room stays lit, exactly as on a motion event.
        """
        self._apply_motion_on(reapply_diverged=True)

    def _apply_motion_on(self, *, reapply_diverged: bool) -> None:
        """Shared motion turn-on logic.

        ``reapply_diverged`` is the release-hold path: a controlled light that
        diverges from the night target is re-applied instead of held, because
        the hold has already been dropped by the user.
        """
        self._cancel_off_timer()

        # The first motion after entering night re-applies the lights that
        # still carry the previous mode's values instead of holding them as
        # a scene (see the comment on _reapply_instead_of_hold).
        reapply = reapply_diverged or self._reapply_instead_of_hold
        self._reapply_instead_of_hold = False

        lights = self._lights.get_lights_list()
        if not lights:
            return

        lights = self._shared.exclude_held(lights)
        if not lights:
            _LOGGER.debug(
                "[%s] Night motion ON: all lights held, skipping",
                self._instance_name,
            )
            return

        lights_to_turn_on: list[str] = []
        for lid in lights:
            state = self._hass.states.get(lid)
            is_off = state is None or state.state != STATE_ON
            if is_off:
                lights_to_turn_on.append(lid)
            elif self._state_ctrl.is_controlled_by_us(lid):
                # A controlled light that already matches the exact night
                # target needs no re-apply: deep in the night the circadian
                # curve is flat, so re-sending the identical brightness/colour
                # on every motion event is pure noise (and, in the log,
                # "turned on" + N "Expected state" lines per movement). When
                # the values actually drifted — circadian moved, or the dial
                # changed — _matches_target_tightly returns False and we
                # re-apply, so the gradual colour refresh is preserved.
                if self._matches_target_tightly(lid):
                    _LOGGER.debug(
                        "[%s] Night motion ON: %s controlled and already matching, skipping",
                        self._instance_name,
                        lid,
                    )
                    continue
                if self._light_diverges_from_night_target(lid):
                    # A scene or manual override has taken this light over.
                    # Hold it (detected) so the off-timer and later motion
                    # re-applies leave it alone, and the release button can
                    # return the room to night mode. Only our own in-flight
                    # command — a fresh turn_on still inside its grace period
                    # — is left alone without a hold: that is our own ramp,
                    # not an external scene.
                    if reapply:
                        lights_to_turn_on.append(lid)
                        continue
                    if self._shared.is_in_grace_period(lid):
                        continue
                    self._state_ctrl.set_hold([lid], reason=HOLD_REASON_DETECTED)
                    _LOGGER.debug(
                        "[%s] Night motion ON: %s diverged from night target, holding (detected)",
                        self._instance_name,
                        lid,
                    )
                    continue
                lights_to_turn_on.append(lid)
            elif self._light_matches_night_values(lid):
                # Not yet controlled but already matching: adopt it.
                lights_to_turn_on.append(lid)
                _LOGGER.debug(
                    "[%s] Night motion ON: %s already on with matching values",
                    self._instance_name,
                    lid,
                )
            else:
                _LOGGER.debug(
                    "[%s] Night motion ON: %s already on with unexpected values",
                    self._instance_name,
                    lid,
                )
                return

        if not lights_to_turn_on:
            _LOGGER.debug(
                "[%s] Night motion ON: no lights to turn on",
                self._instance_name,
            )
            return

        payload = self.build_light_payload(lights_to_turn_on)
        kelvin = None
        if self._is_control_color_on() and self._circadian.is_enabled():
            kelvin = self._circadian.get_expected_night_kelvin()
        self._shared.light_applier.turn_on(
            lights_to_turn_on,
            payload,
            transition="initial",
            brightness_pct=self._target_brightness() if self._is_control_brightness_on() else None,
            kelvin=kelvin,
        )
        _LOGGER.debug(
            "[%s] Night motion ON: turned on %s",
            self._instance_name,
            lights_to_turn_on,
        )

    def reapply_brightness_to_on_lights(self) -> None:
        """Re-apply the night brightness to the lights that are already on.

        Moving the dial changes what night mode aims at; a light that is
        already on has to follow at once, without waiting for the next motion
        event. Off lights stay off — dimming is not an on switch, motion alone
        decides when the room is lit. Held lights are left alone.
        """
        on_lights = [
            lid
            for lid in self._lights.get_lights_list()
            if (state := self._hass.states.get(lid)) is not None
            and state.state == STATE_ON
        ]
        on_lights = self._shared.exclude_held(on_lights)
        if not on_lights:
            return

        payload = self.build_light_payload(on_lights)
        kelvin = None
        if self._is_control_color_on() and self._circadian.is_enabled():
            kelvin = self._circadian.get_expected_night_kelvin()
        self._shared.light_applier.turn_on(
            on_lights,
            payload,
            transition="tick",
            brightness_pct=self._target_brightness() if self._is_control_brightness_on() else None,
            kelvin=kelvin,
        )
        _LOGGER.debug(
            "[%s] Night dial: re-applied %d%% to %s",
            self._instance_name,
            self._target_brightness(),
            on_lights,
        )

    def handle_motion_off(self) -> None:
        """Night mode: motion/presence cleared -> schedule off timer."""
        _LOGGER.debug(
            "[%s] Night motion OFF: scheduling off timer",
            self._instance_name,
        )
        self._schedule_off_timer()

    def _light_matches_night_values(
        self,
        entity_id: str,
        brightness_tolerance_pct: int = 10,
        kelvin_tolerance: int = 400,
    ) -> bool:
        """True if a light's brightness/colour are within tolerance of night.

        This is the *adoption* test: a light we do not control yet that is
        roughly at the night values is worth adopting and then nudged to the
        exact target. It is deliberately looser than the divergence/hold test
        (:meth:`_light_diverges_from_night_target`), which uses the detector's
        own tolerances so a scene is judged identically on every path.
        """
        state = self._hass.states.get(entity_id)
        if state is None or state.state != STATE_ON:
            return True
        attrs = getattr(state, "attributes", {}) or {}

        target_brightness = (
            self._target_brightness() if self._is_control_brightness_on() else None
        )
        target_kelvin = None
        if self._is_control_color_on() and self._circadian.is_enabled():
            target_kelvin = self._circadian.get_expected_night_kelvin()

        comparison = compare_light_to_target(
            attrs,
            target_brightness,
            target_kelvin,
            brightness_tolerance_pct=brightness_tolerance_pct,
            kelvin_tolerance=kelvin_tolerance,
        )
        return not (comparison.brightness_differs or comparison.color_differs)

    def _light_diverges_from_night_target(self, entity_id: str) -> bool:
        """True when a controlled light strongly diverges from our night target.

        Uses the *same* tolerance as the event-driven detector, so a scene is
        judged identically here and in the light-state-change handler — there
        is no band where the detector says "external" while motion re-applies.
        """
        state = self._hass.states.get(entity_id)
        if state is None or state.state != STATE_ON:
            return False
        attrs = getattr(state, "attributes", {}) or {}

        target_brightness = (
            self._target_brightness() if self._is_control_brightness_on() else None
        )
        target_kelvin = None
        if self._is_control_color_on() and self._circadian.is_enabled():
            target_kelvin = self._circadian.get_expected_night_kelvin()

        comparison = compare_light_to_target(
            attrs,
            target_brightness,
            target_kelvin,
            brightness_tolerance_pct=NIGHT_BRIGHTNESS_TOLERANCE,
            kelvin_tolerance=NIGHT_KELVIN_TOLERANCE,
        )
        return comparison.brightness_differs or comparison.color_differs

    def _matches_target_tightly(self, entity_id: str) -> bool:
        """True only when a light already equals the exact night target.

        This is the re-apply skip test and is deliberately *tight* — rounding
        tolerance only, not the loose adoption tolerances of
        :meth:`_light_matches_night_values`. If the circadian target has moved
        even a little (or the dial changed), this returns False so the next
        motion re-applies the fresh colour/brightness. Missing attributes mean
        "cannot verify", so it re-applies rather than skipping (``strict``).

        Deep at night the circadian curve is flat, so this returns True and
        the redundant re-apply — the log noise — is skipped.
        """
        state = self._hass.states.get(entity_id)
        if state is None or state.state != STATE_ON:
            return False
        attrs = getattr(state, "attributes", {}) or {}

        target_brightness = (
            self._target_brightness() if self._is_control_brightness_on() else None
        )
        target_kelvin = None
        if self._is_control_color_on() and self._circadian.is_enabled():
            target_kelvin = self._circadian.get_expected_night_kelvin()

        comparison = compare_light_to_target(
            attrs,
            target_brightness,
            target_kelvin,
            brightness_tolerance_pct=TIGHT_BRIGHTNESS_TOLERANCE_PCT,
            kelvin_tolerance=TIGHT_KELVIN_TOLERANCE,
            strict=True,
        )
        return not (comparison.brightness_differs or comparison.color_differs)

    def _schedule_off_timer(self) -> None:
        """Schedule turn_off after motion_off_delay."""
        lights = self._lights.get_lights_list()
        if not lights:
            return
        self._motion.schedule_night_motion_off(
            lights, lambda: self._off_timer_result()
        )

    def _cancel_off_timer(self) -> None:
        """Cancel any scheduled motion-off turn_off."""
        self._motion.cancel_night_motion_off_timer()

    def _off_timer_result(self) -> tuple[list[str], str | None]:
        """Called when the motion-off timer fires."""
        if self._motion.has_motion_now():
            return ([], "motion/presence still active")

        # Held lights are never touched; a held-on light is not even in this
        # list, so the off timer leaves it alone until the hold is released.
        lights_to_off = self._shared.exclude_held(self._lights.get_lights_list())

        if not lights_to_off:
            _LOGGER.debug(
                "[%s] Night off timer: nothing to turn off",
                self._instance_name,
            )
            return ([], "no lights to turn off")

        self._state_ctrl.unmark_controlled(lights_to_off)
        # Update expected state to OFF before lights actually turn off
        # This prevents false external control detection when state change event fires
        for lid in lights_to_off:
            self._state_ctrl.set_expected_state(lid, on=False)
        return (lights_to_off, None)

    def _apply_night_mode_fallback(self, lights: list[str]) -> None:
        """Apply night mode fallback when motion sensor is not available."""
        lights = self._shared.exclude_held(lights)
        if not lights:
            _LOGGER.debug(
                "[%s] Night: all lights held, skipping fallback",
                self._instance_name,
            )
            return

        fallback = self._config.fallback

        if fallback == NIGHT_FALLBACK_SKIP:
            _LOGGER.debug(
                "[%s] Night: no motion sensor, fallback=skip",
                self._instance_name,
            )
            return

        if fallback == NIGHT_FALLBACK_KEEP:
            _LOGGER.debug(
                "[%s] Night: no motion sensor, fallback=keep",
                self._instance_name,
            )
            return

        if fallback == NIGHT_FALLBACK_OFF:
            _LOGGER.debug(
                "[%s] Night: no motion sensor, fallback=off",
                self._instance_name,
            )
            self._turn_off_lights(lights)
            return

        if fallback == NIGHT_FALLBACK_ON:
            night_brightness = self._target_brightness()
            payload: dict[str, Any] = {"entity_id": lights}

            if self._is_control_brightness_on():
                payload[ATTR_BRIGHTNESS_PCT] = night_brightness

            if self._is_control_color_on() and self._circadian.is_enabled():
                kelvin, elevation = self._circadian.get_kelvin()
                payload[ATTR_COLOR_TEMP_KELVIN] = kelvin
                _LOGGER.debug(
                    "[%s] Night: fallback=on, brightness=%d%%, circadian=%dK",
                    self._instance_name,
                    night_brightness,
                    kelvin,
                )
            else:
                _LOGGER.debug(
                    "[%s] Night: fallback=on, brightness=%d%%",
                    self._instance_name,
                    night_brightness,
                )

            if len(payload) > 1:
                kelvin = payload.get(ATTR_COLOR_TEMP_KELVIN)
                self._shared.light_applier.turn_on(
                    lights,
                    payload,
                    transition="tick",
                    brightness_pct=night_brightness if self._is_control_brightness_on() else None,
                    kelvin=kelvin if self._is_control_color_on() else None,
                )
            return

        _LOGGER.warning(
            "[%s] Night: unknown fallback mode '%s'",
            self._instance_name,
            fallback,
        )

    def _turn_off_lights(self, lights: list[str]) -> None:
        """Turn off lights with transition."""
        self._shared.light_applier.turn_off(lights, transition="tick")
