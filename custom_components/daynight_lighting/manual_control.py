"""External control detection for DayNight Lighting.

Detects when light values or states were changed by an external source (scene,
manual dimmer, other automation). Whenever we apply values, the expected state
of each light is persisted in the state controller. A light state-change event
is then compared against that record, with mode-specific tolerances:
- Lights without a record are not judged (we never commanded them)
- A short grace period after our own commands covers async latency
- The record survives restarts, so a reboot causes no false positives

A detected intervention is written into the state controller's ``held_lights``
with the ``"detected"`` reason. There is no timer and no stability take-over:
a hold ends only through an explicit release or a mode change.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from homeassistant.const import STATE_ON, STATE_UNAVAILABLE, STATE_UNKNOWN

from .domain.brightness import brightness_to_pct
from .domain.colorimetry import (
    COLOR_DISTANCE_THRESHOLD_UV,
    color_distance_to_kelvin,
)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from .state_controller import StateController

_LOGGER = logging.getLogger(__name__)


@dataclass
class ExpectedState:
    """Expected state for a light based on current conditions."""

    on: bool  # Whether light should be on
    brightness_pct: int | None = None  # Expected brightness (None if not controlling)
    kelvin: int | None = None  # Expected color temp (None if not controlling)


def _mired_to_kelvin(mired: int | None) -> int | None:
    """Convert mired to kelvin, tolerating malformed values.

    A non-numeric or zero mired value is not a usable colour temperature; it
    is reported by some bulbs and must not crash the comparison. Returning
    None means "no colour to compare", so the divergence check falls through
    to the RGB/HS/XY path (or ignores the colour axis).
    """
    if mired is None:
        return None
    try:
        mired_int = int(mired)
    except (TypeError, ValueError):
        return None
    if mired_int == 0:
        return None
    return round(1_000_000 / mired_int)


def _has_color_mode(attrs: dict) -> bool:
    """True when a light's ``color_mode`` is a non-temperature colour mode.

    RGB/HS/XY *values* are handled separately via ``color_distance_to_kelvin``;
    this only covers the rare case where the mode says "colour" but no numeric
    colour is present (which we never command and therefore treat as external).
    """
    return attrs.get("color_mode") in ("rgb", "rgbw", "rgbww", "hs", "xy")


# Mode-specific tolerances for external control detection. Single source of
# truth, shared by the event-driven detector and the night motion handler so
# a scene is judged identically on every path.
# Day mode with LUX sensor: higher tolerance due to constant LUX-based changes
DAY_WITH_SENSOR_BRIGHTNESS_TOLERANCE = 10
DAY_WITH_SENSOR_KELVIN_TOLERANCE = 300
# Day mode without LUX sensor (fixed/circadian): lower tolerance since values are static
DAY_NO_SENSOR_BRIGHTNESS_TOLERANCE = 5
DAY_NO_SENSOR_KELVIN_TOLERANCE = 200
# Night mode: medium tolerance for fixed brightness
NIGHT_BRIGHTNESS_TOLERANCE = 5
NIGHT_KELVIN_TOLERANCE = 200
# Sleep/Wake mode: account for gradual transitions
SLEEP_WAKE_BRIGHTNESS_TOLERANCE = 8
SLEEP_WAKE_KELVIN_TOLERANCE = 250
# Tight "already exactly at target" tolerances for the night re-apply skip.
# The old check compared mired to mired with a 5-mired slack; at night colour
# temperatures (~2300-2700K) that is ~26-36K, so 30K reproduces it while the
# comparison itself stays in a single Kelvin space.
TIGHT_BRIGHTNESS_TOLERANCE_PCT = 1
TIGHT_KELVIN_TOLERANCE = 30


@dataclass(frozen=True)
class LightComparison:
    """Result of comparing a light's attributes to a target value.

    ``brightness_differs`` / ``color_differs`` are the *divergence* flags:
    True means the light reports a value outside tolerance and is therefore
    not what we commanded. ``actual_brightness_pct`` / ``actual_kelvin`` carry
    the observed values for logging; they are None when the light reports
    nothing to compare (off/zero brightness, or an RGB/HS/XY colour that has
    no single Kelvin equivalent).
    """

    brightness_differs: bool = False
    color_differs: bool = False
    actual_brightness_pct: int | None = None
    actual_kelvin: int | None = None


def compare_light_to_target(
    attrs: dict,
    target_brightness_pct: int | None,
    target_kelvin: int | None,
    *,
    brightness_tolerance_pct: int,
    kelvin_tolerance: int,
    check_brightness: bool = True,
    check_color: bool = True,
    strict: bool = False,
) -> LightComparison:
    """Compare a light's reported attributes to a target value.

    The single source of truth for "is this light's brightness/colour different
    from the value we aim at". Both the event-driven detector and the night
    motion handler call this, so a scene is judged identically regardless of
    which path notices it first. A ``target_*`` of None (or its ``check_*``
    flag off) disables that axis.

    With ``strict`` a missing or unparseable value counts as a divergence, so
    the result answers "does it *exactly* match" instead of the lenient "does
    it *clearly* differ". The night re-apply skip uses this: an attribute it
    cannot verify must be re-applied rather than skipped.
    """
    brightness_differs = False
    color_differs = False
    actual_brightness_pct: int | None = None
    actual_kelvin: int | None = None

    if check_brightness and target_brightness_pct is not None:
        brightness_raw = attrs.get("brightness")
        if brightness_raw is None:
            if strict:
                brightness_differs = True
        else:
            actual_brightness_pct = brightness_to_pct(brightness_raw)
            if actual_brightness_pct is None or actual_brightness_pct <= 0:
                if strict:
                    brightness_differs = True
            elif abs(actual_brightness_pct - target_brightness_pct) > brightness_tolerance_pct:
                brightness_differs = True

    if check_color and target_kelvin is not None:
        color_mired = attrs.get("color_temp")
        actual_kelvin = _mired_to_kelvin(color_mired)
        if actual_kelvin is not None:
            if abs(actual_kelvin - target_kelvin) > kelvin_tolerance:
                color_differs = True
        else:
            dist = color_distance_to_kelvin(attrs, target_kelvin)
            if dist is not None:
                if dist > COLOR_DISTANCE_THRESHOLD_UV:
                    color_differs = True
            elif _has_color_mode(attrs) or strict:
                color_differs = True

    return LightComparison(
        brightness_differs=brightness_differs,
        color_differs=color_differs,
        actual_brightness_pct=actual_brightness_pct,
        actual_kelvin=actual_kelvin,
    )


class ManualControlDetector:
    """Detects external control by comparing actual state to expected state.

    The expected state is what we last applied to a light, persisted by the
    state controller. Tolerances depend on the mode, because LUX regulation
    and sleep/wake ramps legitimately move values between two commands.
    """

    # Default tolerances (fallback)
    DEFAULT_BRIGHTNESS_TOLERANCE_PCT = 5
    DEFAULT_KELVIN_TOLERANCE = 200

    # Grace period after we apply values (seconds)
    # Only needs to cover async command latency (3-5s), not tick interval
    DEFAULT_GRACE_PERIOD_SEC = 5

    @classmethod
    def get_tolerances_for_mode(
        cls,
        mode: str,
        has_lux_sensor: bool,
    ) -> tuple[int, int]:
        """Get brightness and kelvin tolerances for a given mode.

        Args:
            mode: Current mode (day, night, sleep, wakeup)
            has_lux_sensor: Whether a LUX sensor is configured

        Returns:
            Tuple of (brightness_tolerance_pct, kelvin_tolerance)
        """
        if mode == "day":
            if has_lux_sensor:
                return (DAY_WITH_SENSOR_BRIGHTNESS_TOLERANCE, DAY_WITH_SENSOR_KELVIN_TOLERANCE)
            return (DAY_NO_SENSOR_BRIGHTNESS_TOLERANCE, DAY_NO_SENSOR_KELVIN_TOLERANCE)

        if mode in ("sleep", "wakeup"):
            return (SLEEP_WAKE_BRIGHTNESS_TOLERANCE, SLEEP_WAKE_KELVIN_TOLERANCE)

        # Night mode default
        return (NIGHT_BRIGHTNESS_TOLERANCE, NIGHT_KELVIN_TOLERANCE)

    def __init__(
        self,
        instance_name: str,
    ) -> None:
        """Initialize the detector.

        Args:
            instance_name: Instance name for logging
        """
        self._instance_name = instance_name

        # Grace period tracking - lights we recently applied values to
        self._last_applied_time: dict[str, datetime] = {}
        self._grace_period_sec = self.DEFAULT_GRACE_PERIOD_SEC

    def mark_applied(self, lights: list[str]) -> None:
        """Mark lights as recently having values applied by us.

        These lights will be excluded from external control detection
        for the grace period (default 5 seconds) to avoid race conditions
        where we detect our own in-flight commands as external control.
        """
        now = datetime.now(timezone.utc)
        for lid in lights:
            self._last_applied_time[lid] = now

    def is_in_grace_period(self, light_id: str) -> bool:
        """Check if light was recently applied and is still in grace period."""
        applied_time = self._last_applied_time.get(light_id)
        if applied_time is None:
            return False
        elapsed = (datetime.now(timezone.utc) - applied_time).total_seconds()
        if elapsed < self._grace_period_sec:
            return True
        # Clean up expired entry
        del self._last_applied_time[light_id]
        return False

    def check_external_control(
        self,
        hass: HomeAssistant,
        lights: list[str],
        state_ctrl: StateController,
        check_brightness: bool = True,
        check_color: bool = True,
        brightness_tolerance_pct: int | None = None,
        kelvin_tolerance: int | None = None,
    ) -> list[str]:
        """Check if any light differs from persisted expected state.

        Compares actual light state to the persisted expected state that was
        recorded when we last applied values. Lights without persisted state
        are skipped (no expected values to compare against).

        Args:
            hass: Home Assistant instance
            lights: List of light entity IDs to check
            state_ctrl: State controller for persisted expected states
            check_brightness: Whether to check brightness (Control Brightness setting)
            check_color: Whether to check color temperature (Control Color setting)
            brightness_tolerance_pct: Tolerance for brightness comparison
            kelvin_tolerance: Tolerance for color temperature comparison

        Returns:
            List of light entity IDs that differ from expected (external control)
        """
        # Use default tolerances if not specified
        if brightness_tolerance_pct is None:
            brightness_tolerance_pct = self.DEFAULT_BRIGHTNESS_TOLERANCE_PCT
        if kelvin_tolerance is None:
            kelvin_tolerance = self.DEFAULT_KELVIN_TOLERANCE

        external_lights: list[str] = []

        for lid in lights:
            # Skip lights we recently applied values to (grace period)
            if self.is_in_grace_period(lid):
                continue

            # Get persisted expected state for this light
            expected = state_ctrl.get_expected_state(lid)
            if expected is None:
                # No expected state recorded - skip this light
                # (we don't know what values to expect)
                continue

            state = hass.states.get(lid)
            if state is None:
                continue

            # A light that is briefly unreachable (unavailable/unknown) is not
            # an external intervention: no one switched it off, the device just
            # dropped off the network. Treating it as OFF would produce a false
            # "detected" hold, so skip it until the device reports a real state.
            if state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
                continue

            actual_on = state.state == STATE_ON
            expected_on = expected.get("on", False)

            # Check on/off mismatch
            if expected_on != actual_on:
                if expected_on:
                    # Expected ON but actual OFF -> external turned off
                    _LOGGER.debug(
                        "[%s] External control: %s is OFF (expected ON)",
                        self._instance_name,
                        lid,
                    )
                else:
                    # Expected OFF but actual ON -> external turned on
                    _LOGGER.debug(
                        "[%s] External control: %s is ON (expected OFF)",
                        self._instance_name,
                        lid,
                    )
                external_lights.append(lid)
                continue

            # Light is in correct on/off state - check attributes if ON
            if not actual_on:
                continue

            attrs = getattr(state, "attributes", {}) or {}

            expected_brightness = expected.get("brightness_pct")
            expected_kelvin = expected.get("kelvin")

            comparison = compare_light_to_target(
                attrs,
                expected_brightness,
                expected_kelvin,
                brightness_tolerance_pct=brightness_tolerance_pct,
                kelvin_tolerance=kelvin_tolerance,
                check_brightness=check_brightness,
                check_color=check_color,
            )

            if comparison.brightness_differs:
                _LOGGER.debug(
                    "[%s] External control: %s brightness %s%% != expected %s%%",
                    self._instance_name,
                    lid,
                    comparison.actual_brightness_pct,
                    expected_brightness,
                )
            if comparison.color_differs:
                if comparison.actual_kelvin is not None:
                    _LOGGER.debug(
                        "[%s] External control: %s color %dK != expected %dK",
                        self._instance_name,
                        lid,
                        comparison.actual_kelvin,
                        expected_kelvin,
                    )
                else:
                    # An RGB/HS/XY colour (e.g. Hue) or a colour mode we never
                    # command — a deviation from the white we commanded.
                    _LOGGER.debug(
                        "[%s] External control: %s shows a different colour (expected %sK)",
                        self._instance_name,
                        lid,
                        expected_kelvin,
                    )

            # Report external control if EITHER brightness OR color differs
            if comparison.brightness_differs or comparison.color_differs:
                external_lights.append(lid)

        return external_lights
