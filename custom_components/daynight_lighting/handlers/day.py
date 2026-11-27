"""Day mode handler for DayNight Lighting.

Handles day mode: LUX-based brightness with circadian color control.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from homeassistant.components.light import ATTR_BRIGHTNESS_PCT, ATTR_COLOR_TEMP_KELVIN

from ..config import DayModeConfig
from ..const import (
    DAY_FALLBACK_CIRCADIAN_ONLY,
    DAY_FALLBACK_FIXED,
    DAY_FALLBACK_OFF,
    DAY_FALLBACK_SKIP,
)
from ..context import SharedHandlerDeps
from ..domain.brightness import (
    apply_weather_modifier,
    brightness_to_pct,
    feedback_gain_bound,
    lux_to_brightness_pct,
)
from ..manual_control import ExpectedState
from ..protocols import ColorProvider
from .base import BaseModeHandler

if TYPE_CHECKING:
    from ..illuminance import IlluminanceReader
    from ..weather import WeatherReader

__all__ = ["DayModeHandler"]

_LOGGER = logging.getLogger(__name__)


class DayModeHandler(BaseModeHandler):
    """Handles day mode: LUX-based brightness, circadian color."""

    def __init__(
        self,
        shared: SharedHandlerDeps,
        config: DayModeConfig,
        illuminance: IlluminanceReader,
        weather: WeatherReader,
        circadian: ColorProvider,
    ) -> None:
        """Initialize day mode handler.

        Args:
            shared: Shared dependencies (hass, instance_name, lights, etc.)
            config: Day mode configuration
            illuminance: Illuminance reader for LUX sensor
            weather: Weather reader for brightness modifiers
            circadian: Color provider for circadian temperature
        """
        super().__init__(shared)
        self._config = config
        self._illuminance = illuminance
        self._weather = weather
        self._circadian = circadian
        self._last_applied_kelvin: int | None = None
        self._effective_on: bool | None = None
        self._effective_brightness: int | None = None
        self._pending_on: bool | None = None
        self._pending_since: datetime | None = None
        self._last_measurement: tuple[Any, ...] = ()

    def tick(self) -> None:
        """Execute day mode tick: apply the day values.

        External control is detected event-driven by the main switch and
        written into ``held_lights``; the per-light filtering happens in
        :meth:`_apply_day_mode` via ``exclude_held``.
        """
        self._apply_day_mode()

    def enter(self, previous_mode: str | None) -> None:
        """Called when entering day mode."""
        # Note: day mode is applied by tick() on next cycle
        # This avoids duplicate commands when transitioning from other modes
        self.forget_applied_values()

    def exit(self, next_mode: str) -> None:
        """Called when exiting day mode."""
        self._forget_switch_state()

    def _forget_switch_state(self) -> None:
        """Drop the committed and the pending on/off state.

        Seeding it again from the lights is the honest restart: whatever this
        handler remembers about on/off describes the lights only as long as
        nobody else has touched them.
        """
        self._effective_on = None
        self._effective_brightness = None
        self._pending_on = None
        self._pending_since = None
        self._last_measurement = ()

    def forget_applied_values(self) -> None:
        """Drop the last applied brightness and colour.

        Day mode is the one mode that damps: it only sends a new brightness
        when it differs from the last one *we* sent. After somebody else has
        been at the lights that reference is wrong, and on a bright day the
        LUX-derived target barely moves — so without forgetting, every tick
        would decide it is already at its target and skip.

        The brightness offset is not a memory of a command, it is what
        somebody dialled in, so it deliberately survives.
        """
        self._illuminance.forget_applied_brightness()
        self._last_applied_kelvin = None
        # The remembered on/off state is a memory of our own commands too, so
        # an intervention invalidates it as well; without this reset the next
        # expected-state read could report the state from before the
        # intervention, and a fresh dwell would be anchored to it (V28).
        self._forget_switch_state()

    def target_fixed_brightness(self) -> int:
        """Fixed day brightness in effect: dialled, else the configured value.

        Single point of access, so that the value the lights are set to and
        the value they are checked against cannot drift apart — a mismatch
        there would report our own dimming as somebody else's doing.
        """
        dialled = self._shared.get_day_brightness()
        if dialled is None:
            return self._config.fixed_brightness_pct
        return dialled

    def calculate_expected_state(self) -> ExpectedState:
        """Calculate expected light state based on current conditions.

        Pending LUX transitions must not look like external interventions.
        Once applied, report the values actually sent, including values kept
        by the brightness and colour dampers. Before the first measurement,
        retain the existing fallback semantics.
        """
        lux = self._illuminance.get_lux()
        if lux is not None and self._config.switch_dwell_min > 0:
            self._remember_effective_state(self._lights.get_lights_list())
        if lux is not None and self._effective_on is not None:
            return ExpectedState(
                on=self._effective_on,
                brightness_pct=(
                    self._effective_brightness
                    if self._effective_on and self._is_control_brightness_on() else None
                ),
                kelvin=(
                    self._last_applied_kelvin
                    if self._effective_on and self._is_control_color_on() else None
                ),
            )

        # Determine if lights should be on
        if lux is None:
            # No LUX sensor - use fallback behavior
            if self._config.fallback == DAY_FALLBACK_OFF:
                return ExpectedState(on=False)
            if self._config.fallback == DAY_FALLBACK_SKIP:
                return ExpectedState(on=False)
            # For circadian_only and fixed, lights should be on
            on = True
        else:
            # LUX-based on/off
            pct = self.get_brightness_pct()
            on = pct is not None

        if not on:
            return ExpectedState(on=False)

        # Calculate expected brightness
        brightness_pct = None
        if self._is_control_brightness_on():
            if lux is not None:
                brightness_pct = self.get_brightness_pct()
            elif self._config.fallback == DAY_FALLBACK_FIXED:
                brightness_pct = self.target_fixed_brightness()

        # Calculate expected color
        kelvin = None
        if self._is_control_color_on() and self._circadian.is_enabled():
            kelvin, _ = self._circadian.get_kelvin()

        return ExpectedState(
            on=True,
            brightness_pct=brightness_pct,
            kelvin=kelvin,
        )

    def get_brightness_pct(self) -> int | None:
        """Brightness from the LUX reading; None is off."""
        return self._lux_curve_pct()

    def max_brightness(self) -> int:
        """The brightest the day curve sets (LUX at or below lux_on)."""
        return self._config.max_brightness

    def _lux_curve_pct(self) -> int | None:
        """Brightness percentage from the LUX curve alone."""
        lux = self._illuminance.get_lux()
        if lux is None:
            return None

        lux_on = self._config.lux_on
        lux_off = self._config.lux_off
        day_min = self._config.min_brightness
        day_max = self._config.max_brightness

        return lux_to_brightness_pct(lux, lux_on, lux_off, day_min, day_max)

    def build_light_payload(
        self,
        lights: list[str],
        pct: int,
        kelvin: int | None = None,
        include_brightness: bool = True,
        include_color: bool = True,
    ) -> dict[str, Any] | None:
        """Build light.turn_on payload for day mode."""
        payload: dict[str, Any] = {"entity_id": lights}

        if include_brightness and self._is_control_brightness_on():
            payload[ATTR_BRIGHTNESS_PCT] = pct

        if include_color and kelvin is not None and self._is_control_color_on():
            payload[ATTR_COLOR_TEMP_KELVIN] = kelvin

        return payload if len(payload) > 1 else None

    def _weathered(self, pct: int) -> int:
        """Apply the weather brightness modifier, if weather is enabled."""
        if not self._weather.is_enabled():
            return pct
        modifier = self._weather.get_brightness_modifier()
        result = apply_weather_modifier(
            pct, modifier, self._config.min_brightness, self._config.max_brightness
        )
        if result != pct:
            _LOGGER.debug(
                "[%s] Day: weather modifier %.2fx (%s) -> %d%% -> %d%%",
                self._instance_name,
                modifier,
                self._weather.get_current_condition() or "unknown",
                pct,
                result,
            )
        return result

    def _should_apply_kelvin(self, kelvin: int) -> bool:
        """Check if kelvin should be applied based on change threshold."""
        if self._last_applied_kelvin is None:
            return True
        delta = abs(kelvin - self._last_applied_kelvin)
        return delta >= 50

    def _remember_effective_state(self, lights: list[str]) -> None:
        """Seed the in-memory state from the lights, never from a pending target."""
        if self._effective_on is not None:
            return
        on_states = [
            state
            for light in lights
            if (state := self._hass.states.get(light)) is not None
            and state.state == "on"
        ]
        self._effective_on = bool(on_states)
        if on_states:
            self._effective_brightness = brightness_to_pct(
                on_states[0].attributes.get("brightness")
            )
            self._last_applied_kelvin = on_states[0].attributes.get("color_temp_kelvin")

    def _dwelled_on(self, target_on: bool, lights: list[str]) -> bool:
        """Release a transition only on a fresh measurement after its deadline."""
        if self._config.switch_dwell_min == 0:
            return target_on
        self._remember_effective_state(lights)
        # Like IlluminanceReader's smoothing, consume each immutable HA state
        # object only once. Minute/sun ticks are not new LUX measurements.
        measurement = tuple(
            self._hass.states.get(entity_id)
            for entity_id in self._illuminance.get_light_sensor_entities()
        )
        if len(measurement) == len(self._last_measurement) and all(
            current is previous
            for current, previous in zip(measurement, self._last_measurement)
        ):
            return bool(self._effective_on)
        self._last_measurement = measurement
        if target_on == self._effective_on:
            self._pending_on = None
            self._pending_since = None
            return target_on
        now = datetime.now()
        if self._pending_on != target_on:
            self._pending_on = target_on
            self._pending_since = now
        if self._pending_since is not None and now >= (
            self._pending_since + timedelta(minutes=self._config.switch_dwell_min)
        ):
            return target_on
        return bool(self._effective_on)

    def _apply_day_mode(self) -> None:
        """Compute desired day-mode values and apply to all lights."""
        lights = self._lights.get_lights_list()
        if not lights:
            _LOGGER.debug(
                "[%s] No lights configured, skip day mode",
                self._instance_name,
            )
            return

        lights = self._shared.exclude_held(lights)
        if not lights:
            _LOGGER.debug(
                "[%s] Day: all lights held, skipping",
                self._instance_name,
            )
            return

        lux = self._illuminance.get_lux()

        if lux is None:
            # Missing measurements cannot establish an uninterrupted LUX target.
            self._pending_on = None
            self._pending_since = None
            self._last_measurement = ()
            self._effective_on = None
            self._effective_brightness = None
            self._apply_day_mode_fallback(lights)
            return

        gain_bound = feedback_gain_bound(
            self._illuminance.get_lux_raw(),
            self._illuminance.get_last_applied_brightness(),
            self._config.lux_on, self._config.lux_off,
            self._config.min_brightness, self._config.max_brightness,
            self._illuminance.get_lux_calibration(),
        )
        pct = self._lux_curve_pct()
        effective_on = self._dwelled_on(pct is not None, lights)
        if not effective_on and pct is not None:
            # A colour-only turn_on would bypass the pending on transition.
            return
        if effective_on and pct is None:
            # Keep the brightness in force, but still allow circadian updates.
            pct = self._effective_brightness or 0
            pending_off = True
        else:
            pending_off = False

        if pct is None:
            _LOGGER.debug(
                "[%s] Day: lux=%.1f -> off, lights=%s",
                self._instance_name,
                lux,
                lights,
            )
            self._turn_off_lights(lights)
            self._illuminance.record_brightness_applied(0, gain_bound=gain_bound)
            self._last_applied_kelvin = None
            self._effective_on = False
            self._effective_brightness = None
            return

        if not pending_off:
            pct = self._weathered(pct)

        # Calculate circadian color ALWAYS
        kelvin: int | None = None
        if self._is_control_color_on() and self._circadian.is_enabled():
            kelvin, elevation = self._circadian.get_kelvin()
            _LOGGER.debug(
                "[%s] Day: circadian %dK (elevation %s)",
                self._instance_name,
                kelvin,
                f"{elevation:.1f}deg" if elevation is not None else "n/a",
            )

        # Decide what needs updating
        brightness_needs_update = (
            not pending_off and self._illuminance.should_apply_brightness(pct)
        )
        color_needs_update = kelvin is not None and self._should_apply_kelvin(kelvin)

        if not brightness_needs_update and not color_needs_update:
            return

        # The damper applies brightness and colour independently, so one can
        # be sent while the other is skipped. The expected state and the
        # monitoring sensors must record what the light actually has now — the
        # freshly applied value where sent, the last sent value where skipped
        # — not the computed value that never went out.
        applied_brightness = (
            pct if brightness_needs_update
            else self._effective_brightness
        )
        applied_kelvin = kelvin if color_needs_update else self._last_applied_kelvin

        # Some lights (notably Hue) drop to a low brightness when they receive
        # a colour-only update. Whenever a colour change goes out, re-affirm
        # the current brightness so the light always receives brightness and
        # colour together instead of colour alone.
        send_brightness = (
            brightness_needs_update
            or (color_needs_update and applied_brightness is not None)
        )

        _LOGGER.debug(
            "[%s] Day: lux=%s -> brightness %d%% %s, lights=%s",
            self._instance_name,
            f"{lux:.1f}" if lux is not None else "?",
            pct,
            "(update)" if brightness_needs_update else "(stable)",
            lights,
        )

        payload = self.build_light_payload(
            lights,
            applied_brightness if applied_brightness is not None else pct,
            kelvin,
            include_brightness=send_brightness,
            include_color=color_needs_update,
        )

        if payload is not None:
            self._shared.light_applier.turn_on(
                lights,
                payload,
                transition="tick",
                brightness_pct=applied_brightness if self._is_control_brightness_on() else None,
                kelvin=applied_kelvin if self._is_control_color_on() else None,
            )

            self._effective_on = True
            self._effective_brightness = applied_brightness
            if brightness_needs_update:
                self._illuminance.record_brightness_applied(pct, gain_bound=gain_bound)
            if color_needs_update and kelvin is not None:
                self._last_applied_kelvin = kelvin
        else:
            _LOGGER.debug(
                "[%s] Day: Control Brightness and Color both off, skipping",
                self._instance_name,
            )

    def _apply_day_mode_fallback(self, lights: list[str]) -> None:
        """Apply day mode fallback when LUX sensor is not available."""
        fallback = self._config.fallback

        if fallback == DAY_FALLBACK_SKIP:
            _LOGGER.debug(
                "[%s] Day: no LUX sensor, fallback=skip, doing nothing",
                self._instance_name,
            )
            return

        if fallback == DAY_FALLBACK_OFF:
            _LOGGER.debug(
                "[%s] Day: no LUX sensor, fallback=off, turning lights off",
                self._instance_name,
            )
            self._turn_off_lights(lights)
            return

        if fallback == DAY_FALLBACK_CIRCADIAN_ONLY:
            if not self._is_control_color_on() or not self._circadian.is_enabled():
                _LOGGER.debug(
                    "[%s] Day: fallback=circadian_only but circadian disabled",
                    self._instance_name,
                )
                return

            kelvin, elevation = self._circadian.get_kelvin()
            payload: dict[str, Any] = {
                "entity_id": lights,
                ATTR_COLOR_TEMP_KELVIN: kelvin,
            }
            _LOGGER.debug(
                "[%s] Day: circadian %dK (elevation %s), fallback=circadian_only",
                self._instance_name,
                kelvin,
                f"{elevation:.1f}deg" if elevation is not None else "n/a",
            )
            self._shared.light_applier.turn_on(
                lights, payload, transition="tick", kelvin=kelvin
            )
            return

        if fallback == DAY_FALLBACK_FIXED:
            pct = self.target_fixed_brightness()
            payload = {"entity_id": lights}
            kelvin = None  # Initialize to avoid UnboundLocalError

            if self._is_control_brightness_on():
                payload[ATTR_BRIGHTNESS_PCT] = pct

            if self._is_control_color_on() and self._circadian.is_enabled():
                kelvin, elevation = self._circadian.get_kelvin()
                payload[ATTR_COLOR_TEMP_KELVIN] = kelvin
                _LOGGER.debug(
                    "[%s] Day: fallback=fixed, brightness=%d%%, circadian=%dK",
                    self._instance_name,
                    pct,
                    kelvin,
                )
            else:
                _LOGGER.debug(
                    "[%s] Day: fallback=fixed, brightness=%d%%",
                    self._instance_name,
                    pct,
                )

            if len(payload) > 1:
                self._shared.light_applier.turn_on(
                    lights,
                    payload,
                    transition="tick",
                    brightness_pct=pct if self._is_control_brightness_on() else None,
                    kelvin=kelvin if self._is_control_color_on() else None,
                )
            return

        _LOGGER.warning(
            "[%s] Day: unknown fallback mode '%s', skipping",
            self._instance_name,
            fallback,
        )
