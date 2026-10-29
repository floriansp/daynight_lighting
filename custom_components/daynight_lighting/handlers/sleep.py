"""Sleep mode handler for DayNight Lighting.

Handles sleep mode: gradual dimming over time.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any, Callable

from homeassistant.components.light import ATTR_BRIGHTNESS_PCT, ATTR_COLOR_TEMP_KELVIN
from homeassistant.core import callback
from homeassistant.util import dt as dt_util

from ..config import DayModeConfig, NightModeConfig, SleepModeConfig
from ..const import DEFAULT_DAY_MAX_BRIGHTNESS, DEFAULT_NIGHT_BRIGHTNESS
from ..context import SharedHandlerDeps
from ..manual_control import ExpectedState
from ..protocols import ColorProvider
from ..domain.brightness import lux_to_brightness_pct, ramp_value

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from ..illuminance import IlluminanceReader

__all__ = ["SleepModeHandler"]

_LOGGER = logging.getLogger(__name__)


class SleepModeHandler:
    """Handles sleep mode: gradual dimming over time."""

    def __init__(
        self,
        shared: SharedHandlerDeps,
        config: SleepModeConfig,
        illuminance: IlluminanceReader,
        day_mode_config: DayModeConfig | None = None,
        night_mode_config: NightModeConfig | None = None,
        schedule: Any | None = None,
        circadian: ColorProvider | None = None,
    ) -> None:
        """Initialize sleep mode handler.

        Args:
            shared: Shared dependencies (hass, instance_name, lights, etc.)
            config: Sleep mode configuration
            illuminance: Illuminance reader for LUX sensor
            day_mode_config: Day mode config for default brightness
            night_mode_config: Night mode config for auto-value detection
            schedule: Schedule provider for mode determination
            circadian: Color provider for circadian temperature
        """
        self._shared = shared
        self._config = config
        self._illuminance = illuminance
        self._day_mode_config = day_mode_config
        self._night_mode_config = night_mode_config
        self._schedule = schedule
        self._circadian = circadian
        self._sleep_active: bool = False
        self._sleep_block_active: bool = False
        self._sleep_start_time: Any = None
        self._block_auto_clear_timer: asyncio.TimerHandle | None = None
        self._BLOCK_AUTO_CLEAR_HOURS = 2  # Auto-clear sleep block after 2 hours
        # Runtime overrides from service calls
        self._runtime_duration_min: int | None = None
        self._runtime_brightness: int | None = None
        self._runtime_kelvin: int | None = None

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
        """Sleep mode tick: gradual dim, then OFF, then block."""
        if not self._sleep_active:
            self._sleep_active = True
            self._sleep_start_time = dt_util.now()
            _LOGGER.info(
                "[%s] Sleep Mode: Started at %s",
                self._instance_name,
                self._sleep_start_time.strftime("%H:%M:%S"),
            )

        self._apply_sleep_mode()

    def enter(self, previous_mode: str | None) -> None:
        """Called when entering sleep mode."""
        self._sleep_active = True
        self._sleep_start_time = dt_util.now()
        _LOGGER.debug(
            "[%s] Day->Sleep: starting gradual wind-down",
            self._instance_name,
        )

    def forget_applied_values(self) -> None:
        """Nothing to forget: the ramp recomputes from time on every tick.

        The runtime overrides are not a memory of commands, they are what a
        service asked for, so they deliberately survive.
        """

    def exit(self, next_mode: str) -> None:
        """Called when exiting sleep mode."""
        self._sleep_active = False
        self._sleep_block_active = False
        self._sleep_start_time = None
        self._cancel_block_auto_clear_timer()
        # Clear runtime overrides
        self._runtime_duration_min = None
        self._runtime_brightness = None
        self._runtime_kelvin = None

    def calculate_expected_state(self) -> ExpectedState:
        """Calculate expected light state based on current conditions.

        For sleep mode:
        - Light should be ON during dimming phase
        - Light should be OFF after dimming complete (block active)
        - Brightness gradually dims from current to target
        - Color gradually shifts to target kelvin
        """
        # Check if block is active (after dimming complete)
        if self._sleep_block_active:
            return ExpectedState(on=False)

        # Check if sleep is not active
        if not self._sleep_active:
            return ExpectedState(on=False)

        # Calculate current brightness and color
        progress = self.get_progress()
        if progress >= 1.0:
            # Dimming complete, should be transitioning to off
            return ExpectedState(on=False)

        brightness_pct = None
        if self._is_control_brightness_on():
            brightness_pct = self.get_brightness_pct()

        kelvin = None
        if self._is_control_color_on():
            kelvin = self._calculate_dimmed_kelvin(progress)

        return ExpectedState(
            on=True,
            brightness_pct=brightness_pct,
            kelvin=kelvin,
        )

    def get_brightness_pct(self) -> int | None:
        """Calculate current sleep brightness."""
        progress = self.get_progress()
        if progress >= 1.0:
            return None

        # Determine target brightness (with runtime override)
        target_brightness = self._runtime_brightness if self._runtime_brightness is not None else self._config.target_brightness

        # Determine start brightness
        if self._config.use_auto_values:
            start_brightness = self._get_auto_start_brightness()
        else:
            lux = self._illuminance.get_lux()
            if lux is not None:
                start_brightness = lux_to_brightness_pct(
                    lux,
                    target_brightness,  # Use target as lux_on
                    target_brightness + 100,  # lux_off
                    0,  # min
                    100,  # max
                )
                if start_brightness is None:
                    start_brightness = (
                        self._day_mode_config.max_brightness
                        if self._day_mode_config
                        else DEFAULT_DAY_MAX_BRIGHTNESS
                    )
            else:
                start_brightness = (
                    self._day_mode_config.max_brightness
                    if self._day_mode_config
                    else DEFAULT_DAY_MAX_BRIGHTNESS
                )

        brightness_pct = ramp_value(start_brightness, target_brightness, progress)
        return max(0, min(100, brightness_pct))

    def get_progress(self) -> float:
        """Calculate progress through sleep duration (0.0 = start, 1.0 = end)."""
        if not self._sleep_start_time:
            return 0.0

        duration_min = self._get_sleep_duration()
        if duration_min is None:
            _LOGGER.error(
                "[%s] Sleep Mode: duration_min is required",
                self._instance_name,
            )
            return 1.0

        now = dt_util.now()
        elapsed_seconds = (now - self._sleep_start_time).total_seconds()
        total_seconds = duration_min * 60

        if total_seconds <= 0:
            return 1.0

        progress = elapsed_seconds / total_seconds
        return max(0.0, min(1.0, progress))

    def build_light_payload(
        self,
        lights: list[str],
        brightness_pct: int,
        kelvin: int,
    ) -> dict[str, Any] | None:
        """Build light.turn_on payload for sleep mode."""
        payload: dict[str, Any] = {"entity_id": lights}

        if self._is_control_brightness_on():
            payload[ATTR_BRIGHTNESS_PCT] = brightness_pct

        if self._is_control_color_on():
            payload[ATTR_COLOR_TEMP_KELVIN] = kelvin

        return payload if len(payload) > 1 else None

    def _calculate_dimmed_kelvin(self, progress: float) -> int:
        """Calculate kelvin during dimming (returns target kelvin for now)."""
        return self._config.target_kelvin

    def _get_auto_start_brightness(self) -> int:
        """Get auto-detected start brightness based on current mode.

        Day mode: use day max brightness
        Night mode: use night brightness
        """
        if self._schedule is not None:
            is_day = self._schedule.is_day_mode()
        else:
            # Fallback: assume day mode if no schedule
            is_day = True

        if is_day:
            # Day mode: use day max brightness
            brightness = (
                self._day_mode_config.max_brightness
                if self._day_mode_config
                else DEFAULT_DAY_MAX_BRIGHTNESS
            )
            _LOGGER.debug(
                "[%s] Sleep: auto-detect start brightness (day mode) = %d%%",
                self._instance_name,
                brightness,
            )
        else:
            # Night mode: use night brightness
            brightness = (
                self._night_mode_config.brightness
                if self._night_mode_config
                else DEFAULT_NIGHT_BRIGHTNESS
            )
            _LOGGER.debug(
                "[%s] Sleep: auto-detect start brightness (night mode) = %d%%",
                self._instance_name,
                brightness,
            )
        return brightness

    def _get_auto_start_kelvin(self) -> int | None:
        """Get auto-detected start kelvin based on current mode.

        Day mode: use current circadian kelvin
        Night mode: use night circadian kelvin (min_kelvin)
        """
        if self._circadian is None or not self._circadian.is_enabled():
            return None

        if self._schedule is not None:
            is_day = self._schedule.is_day_mode()
        else:
            is_day = True

        if is_day:
            # Day mode: use current circadian kelvin
            kelvin, _ = self._circadian.get_kelvin()
            _LOGGER.debug(
                "[%s] Sleep: auto-detect start kelvin (day mode) = %dK",
                self._instance_name,
                kelvin,
            )
        else:
            # Night mode: use night circadian kelvin (min_kelvin)
            kelvin = self._circadian.get_expected_night_kelvin()
            _LOGGER.debug(
                "[%s] Sleep: auto-detect start kelvin (night mode) = %dK",
                self._instance_name,
                kelvin,
            )
        return kelvin

    def _get_sleep_duration(self) -> int:
        """Get sleep duration, considering runtime overrides."""
        if self._runtime_duration_min is not None:
            return self._runtime_duration_min
        return self._config.duration_min

    def _apply_sleep_mode(self) -> None:
        """Apply Sleep Mode: dim -> OFF -> block."""
        lights = self._lights.get_lights_list()
        if not lights:
            _LOGGER.debug(
                "[%s] No lights configured, skip sleep mode",
                self._instance_name,
            )
            return

        lights = self._shared.exclude_held(lights)
        if not lights:
            _LOGGER.debug(
                "[%s] Sleep: all lights held, skipping",
                self._instance_name,
            )
            return

        progress = self.get_progress()

        if progress >= 1.0:
            _LOGGER.info(
                "[%s] Sleep Mode: Duration complete, turning lights OFF",
                self._instance_name,
            )
            self._shared.light_applier.turn_off(lights, transition="mode")
            self._sleep_active = False
            self._sleep_block_active = True
            self._sleep_start_time = None
            self._schedule_block_auto_clear()
            # Clear runtime overrides
            self._runtime_duration_min = None
            self._runtime_brightness = None
            self._runtime_kelvin = None
            _LOGGER.info(
                "[%s] Sleep Mode: Block active",
                self._instance_name,
            )
            return

        # Determine start brightness
        if self._config.use_auto_values:
            # Auto-detect start values from current mode
            start_brightness = self._get_auto_start_brightness()
            start_kelvin = self._get_auto_start_kelvin()
        else:
            # Use LUX-based brightness as start (original behavior)
            lux = self._illuminance.get_lux()
            if lux is not None:
                start_brightness = lux_to_brightness_pct(
                    lux,
                    self._config.target_brightness,
                    self._config.target_brightness + 100,
                    0,
                    100,
                )
                if start_brightness is None:
                    start_brightness = (
                        self._day_mode_config.max_brightness
                        if self._day_mode_config
                        else DEFAULT_DAY_MAX_BRIGHTNESS
                    )
            else:
                start_brightness = (
                    self._day_mode_config.max_brightness
                    if self._day_mode_config
                    else DEFAULT_DAY_MAX_BRIGHTNESS
                )
            start_kelvin = None  # Will use target_kelvin

        # Apply runtime overrides if provided
        target_brightness = self._runtime_brightness if self._runtime_brightness is not None else self._config.target_brightness
        target_kelvin = self._runtime_kelvin if self._runtime_kelvin is not None else self._config.target_kelvin

        brightness_pct = ramp_value(start_brightness, target_brightness, progress)
        brightness_pct = max(0, min(100, brightness_pct))

        # Interpolate kelvin if we have auto-detected start value
        if start_kelvin is not None and self._is_control_color_on():
            current_kelvin = ramp_value(start_kelvin, target_kelvin, progress)
        else:
            current_kelvin = target_kelvin

        _LOGGER.debug(
            "[%s] Sleep: progress=%.1f%%, brightness=%d%% (start=%d, target=%d), kelvin=%dK (start=%s, target=%d)",
            self._instance_name,
            progress * 100,
            brightness_pct,
            start_brightness,
            target_brightness,
            current_kelvin,
            start_kelvin if start_kelvin is not None else "n/a",
            target_kelvin,
        )

        payload = self.build_light_payload(lights, brightness_pct, current_kelvin)
        if payload is None:
            _LOGGER.debug(
                "[%s] Sleep: Control switches off, skipping",
                self._instance_name,
            )
            return

        self._shared.light_applier.turn_on(
            lights,
            payload,
            transition="tick",
            brightness_pct=brightness_pct if self._is_control_brightness_on() else None,
            kelvin=current_kelvin if self._is_control_color_on() else None,
        )

    def is_block_active(self) -> bool:
        """Check if sleep block is currently active."""
        return self._sleep_block_active

    def _schedule_block_auto_clear(self) -> None:
        """Schedule auto-clear of sleep block after 2 hours."""
        self._cancel_block_auto_clear_timer()

        @callback
        def _auto_clear() -> None:
            self._block_auto_clear_timer = None
            if self._sleep_block_active:
                _LOGGER.info(
                    "[%s] Sleep Mode: Block auto-cleared after %d hours",
                    self._instance_name,
                    self._BLOCK_AUTO_CLEAR_HOURS,
                )
                self._sleep_block_active = False

        delay_seconds = self._BLOCK_AUTO_CLEAR_HOURS * 3600
        self._block_auto_clear_timer = self._hass.loop.call_later(
            delay_seconds, _auto_clear
        )
        _LOGGER.debug(
            "[%s] Sleep Mode: Block auto-clear scheduled in %d hours",
            self._instance_name,
            self._BLOCK_AUTO_CLEAR_HOURS,
        )

    def _cancel_block_auto_clear_timer(self) -> None:
        """Cancel the block auto-clear timer."""
        if self._block_auto_clear_timer is not None:
            self._block_auto_clear_timer.cancel()
            self._block_auto_clear_timer = None

    def clear_block(self) -> None:
        """Clear the sleep block (e.g., on motion or day mode)."""
        if self._sleep_block_active:
            self._sleep_block_active = False
            self._cancel_block_auto_clear_timer()
            _LOGGER.info(
                "[%s] Sleep Mode: Block cleared",
                self._instance_name,
            )

    def interrupt_into_block(self) -> None:
        """End the running wind-down immediately and enter the dark block.

        A ``turn_off`` with ``hold: true`` (a wall button or a foreign app)
        ends the whole ramp: the room goes dark and stays dark until day or
        motion clears the block, exactly as if the dimming had run out.
        """
        self._sleep_active = False
        self._sleep_block_active = True
        self._sleep_start_time = None
        self._runtime_duration_min = None
        self._runtime_brightness = None
        self._runtime_kelvin = None
        self._cancel_block_auto_clear_timer()
        self._schedule_block_auto_clear()
        _LOGGER.info(
            "[%s] Sleep Mode: interrupted by turn_off, block active",
            self._instance_name,
        )

    def is_sleep_active(self) -> bool:
        """Check if sleep dimming is currently active."""
        return self._sleep_active

    def start_with_overrides(
        self,
        duration_min: int | None = None,
        brightness_pct: int | None = None,
        color_temp_kelvin: int | None = None,
    ) -> None:
        """Start sleep mode with runtime parameter overrides.

        Args:
            duration_min: Optional override for sleep duration in minutes
            brightness_pct: Optional override for target brightness
            color_temp_kelvin: Optional override for target kelvin
        """
        self._runtime_duration_min = duration_min
        self._runtime_brightness = brightness_pct
        self._runtime_kelvin = color_temp_kelvin

        # Reset sleep state
        self._sleep_active = True
        self._sleep_start_time = dt_util.now()
        self._sleep_block_active = False

        _LOGGER.info(
            "[%s] Sleep Mode: Started with overrides (duration=%s, brightness=%s, kelvin=%s)",
            self._instance_name,
            duration_min if duration_min is not None else "config",
            brightness_pct if brightness_pct is not None else "config",
            color_temp_kelvin if color_temp_kelvin is not None else "config",
        )

        self._apply_sleep_mode()
