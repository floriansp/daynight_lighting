"""Wake-up mode handler for DayNight Lighting.

Handles wake-up mode: gradual brightening over time.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Callable

from datetime import datetime, timedelta

from homeassistant.components.light import ATTR_BRIGHTNESS_PCT, ATTR_COLOR_TEMP_KELVIN
from homeassistant.util import dt as dt_util

from ..config import DayModeConfig, NightModeConfig, WakeUpModeConfig
from ..const import DEFAULT_DAY_MAX_BRIGHTNESS, DEFAULT_NIGHT_BRIGHTNESS
from ..context import SharedHandlerDeps
from ..domain.brightness import ramp_value
from ..manual_control import ExpectedState
from ..protocols import ColorProvider

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from ..illuminance import IlluminanceReader

__all__ = ["WakeUpModeHandler"]

_LOGGER = logging.getLogger(__name__)


class WakeUpModeHandler:
    """Handles wake-up mode: gradual brightening over time."""

    def __init__(
        self,
        shared: SharedHandlerDeps,
        config: WakeUpModeConfig,
        illuminance: IlluminanceReader,
        schedule: Any,
        circadian: ColorProvider,
        day_mode_config: DayModeConfig | None = None,
        night_mode_config: NightModeConfig | None = None,
    ) -> None:
        """Initialize wake-up mode handler.

        Args:
            shared: Shared dependencies (hass, instance_name, lights, etc.)
            config: Wake-up mode configuration
            illuminance: Illuminance reader for LUX sensor
            schedule: Schedule provider for mode determination
            circadian: Color provider for circadian temperature
            day_mode_config: Day mode config for target brightness
            night_mode_config: Night mode config for target brightness
        """
        self._shared = shared
        self._config = config
        self._illuminance = illuminance
        self._schedule = schedule
        self._circadian = circadian
        self._day_mode_config = day_mode_config
        self._night_mode_config = night_mode_config
        self._wakeup_active: bool = False
        self._wakeup_block_active: bool = False
        self._wakeup_start_time: Any = None
        self._wakeup_service_duration_min: int | None = None
        # Runtime overrides from service calls
        self._runtime_start_brightness: int | None = None
        self._runtime_end_brightness: int | None = None
        self._runtime_end_kelvin: int | None = None

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
        """Wake-up mode tick: gradual brightness ramp."""
        if self._wakeup_block_active:
            _LOGGER.debug(
                "[%s] Wake-up: block active, skipping ramp",
                self._instance_name,
            )
            return
        self._apply_wakeup_mode()
        self._finish_service_wakeup_if_complete()

    def enter(self, previous_mode: str | None) -> None:
        """Called when entering wake-up mode."""
        _LOGGER.debug(
            "[%s] Night->Wake-up: starting gentle brightness ramp",
            self._instance_name,
        )

    def forget_applied_values(self) -> None:
        """Nothing to forget: the ramp recomputes from time on every tick.

        The runtime overrides are not a memory of commands, they are what a
        service asked for, so they deliberately survive.
        """

    def exit(self, next_mode: str) -> None:
        """Called when exiting wake-up mode."""
        self._wakeup_active = False
        self._wakeup_block_active = False
        self._wakeup_start_time = None
        self._wakeup_service_duration_min = None
        # Clear runtime overrides
        self._runtime_start_brightness = None
        self._runtime_end_brightness = None
        self._runtime_end_kelvin = None
        # Clear expected states to prevent false external control detection
        lights = self._lights.get_lights_list()
        for lid in lights:
            self._state_ctrl.set_expected_state(lid, on=False)

    def calculate_expected_state(self) -> ExpectedState:
        """Calculate expected light state based on current conditions.

        For wake-up mode:
        - Light should be ON during the wake-up ramp
        - Light should be OFF when not active
        - Brightness gradually increases from start to target
        - Color is circadian based on current sun elevation
        """
        if not self._wakeup_active:
            return ExpectedState(on=False)

        progress = self.get_progress()
        if progress >= 1.0:
            # Wake-up complete, should transition to next mode
            return ExpectedState(on=False)

        brightness_pct = None
        if self._is_control_brightness_on():
            brightness_pct = self.get_brightness_pct()

        kelvin = None
        if self._is_control_color_on() and self._circadian.is_enabled():
            kelvin, _ = self._circadian.get_kelvin()

        return ExpectedState(
            on=True,
            brightness_pct=brightness_pct,
            kelvin=kelvin,
        )

    def _get_start_brightness(self) -> int:
        """Get start brightness, considering runtime overrides."""
        if self._runtime_start_brightness is not None:
            return self._runtime_start_brightness
        return self._config.start_brightness

    def _get_end_brightness(self) -> int:
        """Get end brightness based on destination mode (auto or config)."""
        # Check runtime override first
        if self._runtime_end_brightness is not None:
            return self._runtime_end_brightness

        # If auto-values enabled, determine from destination mode
        if self._config.use_auto_values:
            end_mode_is_day = self._schedule.is_day_mode()
            if end_mode_is_day:
                brightness = (
                    self._day_mode_config.max_brightness
                    if self._day_mode_config
                    else DEFAULT_DAY_MAX_BRIGHTNESS
                )
                _LOGGER.debug(
                    "[%s] Wake-up: auto-detect end brightness (day mode) = %d%%",
                    self._instance_name,
                    brightness,
                )
            else:
                brightness = (
                    self._night_mode_config.brightness
                    if self._night_mode_config
                    else DEFAULT_NIGHT_BRIGHTNESS
                )
                _LOGGER.debug(
                    "[%s] Wake-up: auto-detect end brightness (night mode) = %d%%",
                    self._instance_name,
                    brightness,
                )
            return brightness

        # Fallback: use configured start_brightness as end (original behavior)
        return self._config.start_brightness

    def _get_end_kelvin(self) -> int | None:
        """Get end kelvin based on destination mode (auto or config)."""
        # Check runtime override first
        if self._runtime_end_kelvin is not None:
            return self._runtime_end_kelvin

        # If auto-values enabled, determine from destination mode
        if self._config.use_auto_values and self._circadian is not None and self._circadian.is_enabled():
            end_mode_is_day = self._schedule.is_day_mode()
            if end_mode_is_day:
                # Day mode: use current circadian kelvin
                kelvin, _ = self._circadian.get_kelvin()
                _LOGGER.debug(
                    "[%s] Wake-up: auto-detect end kelvin (day mode) = %dK",
                    self._instance_name,
                    kelvin,
                )
            else:
                # Night mode: use night circadian kelvin (min_kelvin)
                kelvin = self._circadian.get_expected_night_kelvin()
                _LOGGER.debug(
                    "[%s] Wake-up: auto-detect end kelvin (night mode) = %dK",
                    self._instance_name,
                    kelvin,
                )
            return kelvin

        # Use configured end_kelvin
        return self._config.end_kelvin

    def get_brightness_pct(self) -> int:
        """Calculate current wake-up brightness."""
        progress = self.get_progress()
        start_brightness = self._get_start_brightness()
        end_brightness = self._get_end_brightness()

        brightness_pct = ramp_value(start_brightness, end_brightness, progress)
        return max(1, min(100, brightness_pct))

    def _service_wakeup_progress(self) -> float:
        """Raw progress of the service-triggered ramp, may exceed 1.0."""
        duration_min = self._wakeup_service_duration_min or 30
        elapsed_seconds = (dt_util.now() - self._wakeup_start_time).total_seconds()
        return elapsed_seconds / (duration_min * 60)

    def _finish_service_wakeup_if_complete(self) -> None:
        """Clear the service-triggered ramp once it has run out.

        Called at the end of a tick, after the final ramp value was applied.
        Reading progress must stay free of side effects so that sensors can
        query it without driving the state machine.
        """
        if not (self._wakeup_active and self._wakeup_start_time):
            return
        if self._service_wakeup_progress() < 1.0:
            return

        self._wakeup_active = False
        self._wakeup_start_time = None
        self._wakeup_service_duration_min = None
        _LOGGER.info(
            "[%s] Wake-up Mode: Service-triggered wake-up complete",
            self._instance_name,
        )

    def get_progress(self) -> float:
        """Calculate progress through wake-up ramp (0.0 = start, 1.0 = complete)."""
        now = dt_util.now()

        if self._wakeup_active and self._wakeup_start_time:
            return max(0.0, min(1.0, self._service_wakeup_progress()))

        # Scheduled wake-up: use schedule window
        wakeup_end_time = self._schedule._get_wakeup_end_time()
        duration_min = self._config.duration_min

        today = now.date()
        wakeup_end = datetime.combine(today, wakeup_end_time).replace(tzinfo=now.tzinfo)
        wakeup_start = wakeup_end - timedelta(minutes=duration_min)

        if now.time().hour > 18 and wakeup_end_time.hour < 12:
            wakeup_end += timedelta(days=1)
            wakeup_start += timedelta(days=1)

        total_duration = (wakeup_end - wakeup_start).total_seconds()
        if total_duration <= 0:
            return 0.0

        elapsed = (now - wakeup_start).total_seconds()
        progress = elapsed / total_duration

        return max(0.0, min(1.0, progress))

    def build_light_payload(
        self,
        lights: list[str],
        brightness_pct: int,
        kelvin: int | None,
    ) -> dict[str, Any] | None:
        """Build light.turn_on payload for wake-up mode."""
        payload: dict[str, Any] = {"entity_id": lights}

        if self._is_control_brightness_on():
            payload[ATTR_BRIGHTNESS_PCT] = brightness_pct

        if kelvin is not None and self._is_control_color_on():
            payload[ATTR_COLOR_TEMP_KELVIN] = kelvin

        return payload if len(payload) > 1 else None

    def _apply_wakeup_mode(self) -> None:
        """Apply wake-up: linear ramp from start -> target brightness."""
        lights = self._lights.get_lights_list()
        if not lights:
            _LOGGER.debug(
                "[%s] No lights configured, skip wake-up mode",
                self._instance_name,
            )
            return

        lights = self._shared.exclude_held(lights)
        if not lights:
            _LOGGER.debug(
                "[%s] Wake-up: all lights held, skipping",
                self._instance_name,
            )
            return

        progress = self.get_progress()
        start_brightness = self._get_start_brightness()
        end_brightness = self._get_end_brightness()

        brightness_pct = ramp_value(start_brightness, end_brightness, progress)
        brightness_pct = max(1, min(100, brightness_pct))

        # Determine kelvin based on config (auto or fixed)
        kelvin: int | None = self._get_end_kelvin()
        if kelvin is None and self._is_control_color_on() and self._circadian.is_enabled():
            # Fallback to current circadian if no configured end_kelvin
            kelvin, elevation = self._circadian.get_kelvin()
            _LOGGER.debug(
                "[%s] Wake-up: circadian %dK (elevation %s)",
                self._instance_name,
                kelvin,
                f"{elevation:.1f}deg" if elevation is not None else "n/a",
            )

        _LOGGER.debug(
            "[%s] Wake-up: progress=%.1f%%, brightness=%d%% (start=%d, end=%d), kelvin=%sK",
            self._instance_name,
            progress * 100,
            brightness_pct,
            start_brightness,
            end_brightness,
            kelvin if kelvin is not None else "n/a",
        )

        payload = self.build_light_payload(lights, brightness_pct, kelvin)
        if payload is None:
            _LOGGER.debug(
                "[%s] Wake-up: Control switches off, skipping",
                self._instance_name,
            )
            return

        self._shared.light_applier.turn_on(
            lights,
            payload,
            transition="tick",
            brightness_pct=brightness_pct if self._is_control_brightness_on() else None,
            kelvin=kelvin if self._is_control_color_on() else None,
        )

    def is_service_triggered_active(self) -> bool:
        """Check if service-triggered wake-up is currently active."""
        return self._wakeup_active

    def is_active(self) -> bool:
        """Check if wake-up is currently active (service-triggered or scheduled)."""
        if self._wakeup_block_active:
            return False
        progress = self.get_progress()
        return 0.0 < progress < 1.0

    def start_service_triggered(
        self,
        duration_min: int,
        start_brightness_pct: int | None = None,
        end_brightness_pct: int | None = None,
        color_temp_kelvin: int | None = None,
    ) -> None:
        """Start service-triggered wake-up mode immediately.

        Args:
            duration_min: Duration of wake-up ramp in minutes
            start_brightness_pct: Optional override for start brightness
            end_brightness_pct: Optional override for end brightness
            color_temp_kelvin: Optional override for end kelvin
        """
        if self._wakeup_active:
            _LOGGER.info(
                "[%s] Wake-up Mode already active - ignoring start request",
                self._instance_name,
            )
            return

        # Set runtime overrides
        self._runtime_start_brightness = start_brightness_pct
        self._runtime_end_brightness = end_brightness_pct
        self._runtime_end_kelvin = color_temp_kelvin

        self._wakeup_active = True
        self._wakeup_start_time = dt_util.now()
        self._wakeup_service_duration_min = duration_min

        _LOGGER.info(
            "[%s] Wake-up Mode: Started immediately (duration: %d min, start=%s, end=%s, kelvin=%s)",
            self._instance_name,
            duration_min,
            start_brightness_pct if start_brightness_pct is not None else "config",
            end_brightness_pct if end_brightness_pct is not None else "auto",
            color_temp_kelvin if color_temp_kelvin is not None else "config",
        )

        self._apply_wakeup_mode()

    def interrupt_into_block(self) -> None:
        """End the running wake-up ramp immediately and hold the lights off.

        A ``turn_off`` with ``hold: true`` (a wall button or a foreign app)
        ends the whole ramp: the lights stay off until the mode is released.
        """
        self._wakeup_active = False
        self._wakeup_block_active = True
        self._wakeup_start_time = None
        self._wakeup_service_duration_min = None
        self._runtime_start_brightness = None
        self._runtime_end_brightness = None
        self._runtime_end_kelvin = None
        _LOGGER.info(
            "[%s] Wake-up Mode: interrupted by turn_off, block active",
            self._instance_name,
        )

    def is_wakeup_block_active(self) -> bool:
        """Whether the wake-up block (turn_off interrupt) is currently active."""
        return self._wakeup_block_active

    def clear_wakeup_block(self) -> None:
        """Clear the wake-up block (e.g., on release or day mode)."""
        if self._wakeup_block_active:
            self._wakeup_block_active = False
            _LOGGER.info(
                "[%s] Wake-up Mode: Block cleared",
                self._instance_name,
            )
