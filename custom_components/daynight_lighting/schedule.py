"""Day/night schedule for DayNight Lighting: when is day mode (LUX) vs night mode (motion).

This module acts as an adapter between Home Assistant's time/sun entities
and the pure domain schedule calculation functions.
"""

from __future__ import annotations

import logging
from datetime import time as dt_time

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .config import NightModeConfig, SleepModeConfig, WakeUpModeConfig
from .const import (
    MODE_DAY,
    MODE_NIGHT,
    MODE_SLEEP,
    MODE_WAKEUP,
)
from .domain import (
    Mode,
    calculate_progress_ratio,
    calculate_time_after,
    calculate_time_before,
    determine_mode,
    is_in_time_window,
)
from .domain.schedule import ModeDeterminationContext

_LOGGER = logging.getLogger(__name__)


class DayNightSchedule:
    """Decides whether we are in day mode (LUX-based) or night mode (motion-based)."""

    def __init__(
        self,
        hass: HomeAssistant,
        night_mode: NightModeConfig,
        sleep_mode: SleepModeConfig,
        wakeup_mode: WakeUpModeConfig,
    ) -> None:
        self._hass = hass
        self._night_mode = night_mode
        self._sleep_mode = sleep_mode
        self._wakeup_mode = wakeup_mode
        self._validate_config_edge_cases()

    def _get_night_start_time(self) -> dt_time:
        """Configured night mode start time."""
        return dt_time(*self._night_mode.start_time)

    def _is_sun_above_horizon(self) -> bool:
        """True if sun.sun state is above_horizon."""
        sun = self._hass.states.get("sun.sun")
        return sun is not None and sun.state == "above_horizon"

    def _is_evening_after_sunset(self) -> bool:
        """True when the sun has already set today (evening, not morning).

        When the sun is below the horizon and the current time is before
        ``night_start``, we need to distinguish:

        * **Morning** (before sunrise) → still night mode.
        * **Evening** (after sunset, before ``night_start``) → day mode
          continues until the configured time.

        Uses ``sun.sun``'s ``next_rising`` attribute: if next sunrise is
        **tomorrow** → we are in the evening (sun already set today).
        If next sunrise is **today** → we are in the morning (sun hasn't
        risen yet).
        """
        sun = self._hass.states.get("sun.sun")
        if sun is None:
            return False
        next_rising_str = sun.attributes.get("next_rising")
        if not next_rising_str:
            return False
        next_rising = dt_util.parse_datetime(str(next_rising_str))
        if next_rising is None:
            return False
        now_local = dt_util.now()
        rising_local = dt_util.as_local(next_rising)
        # Sunrise tomorrow → evening (sun already set) → DAY continues
        # Sunrise today    → morning (sun not yet up)  → NIGHT
        return rising_local.date() != now_local.date()

    def is_day_mode(self) -> bool:
        """True when in day window (LUX-based); False when in night window (motion-based)."""
        mode = self._night_mode.start_trigger
        if mode == "at_time":
            now = dt_util.now().time()
            night_start = self._get_night_start_time()
            # Past configured night start time → always night
            if now >= night_start:
                return False
            # Sun is up and before night start → always day
            if self._is_sun_above_horizon():
                return True
            # Sun below horizon, before night_start.
            # Evening after sunset → day mode continues until night_start.
            # Morning before sunrise → still night mode.
            return self._is_evening_after_sunset()
        # sun_below_horizon: day when sun above horizon, night when sun below (sunset = night start)
        return self._is_sun_above_horizon()

    def get_mode_and_time_for_log(self) -> tuple[str, str]:
        """Return (mode, night_start_str) for debug logging."""
        t = self._get_night_start_time()
        return (self._night_mode.start_trigger, t.strftime("%H:%M"))

    def _build_mode_context(self) -> ModeDeterminationContext:
        """Build mode determination context from Home Assistant state.

        This is the adapter side - it reads from HA entities and builds
        a pure context object for domain calculations.
        """
        # Get current time
        now = dt_util.now().time()

        # Get sun state (adapter side - reads from HA)
        sun_above_horizon = self._is_sun_above_horizon()
        next_sunrise_today = not self._is_evening_after_sunset() if not sun_above_horizon else None

        # Build context
        return ModeDeterminationContext(
            current_time=now,
            sun_above_horizon=sun_above_horizon,
            next_sunrise_today=next_sunrise_today,
            sleep_enabled=self._sleep_mode.enabled,
            sleep_start_time=self._get_sleep_start_time() if self._sleep_mode.enabled else None,
            sleep_duration_min=self._sleep_mode.duration_min if self._sleep_mode.enabled else 0,
            wakeup_enabled=self._wakeup_mode.enabled,
            wakeup_time=self._get_wakeup_end_time() if self._wakeup_mode.enabled else None,
            wakeup_duration_min=self._wakeup_mode.duration_min if self._wakeup_mode.enabled else 0,
            night_start_time=self._get_night_start_time(),
            night_start_trigger=self._night_mode.start_trigger,
        )

    def get_current_mode(self) -> str:
        """Return current mode: MODE_SLEEP | MODE_WAKEUP | MODE_DAY | MODE_NIGHT.

        Wake-up 2.0 (v1.5.0): Independent override modes with priority order.

        Mode priority (independent overrides):
        1. Sleep Mode 2.0 - "go to bed" override (checked first)
        2. Wake-up Mode 2.0 - "gradual wake" override (checked second)
        3. Day Mode / Night Mode - Base time-based modes

        Time windows:
        - Sleep: sleep_start to sleep_start + duration (independent override)
        - Wake-up: wakeup_time - duration to wakeup_time (independent override)
        - Day: sunrise/configured-time to sleep_start (LUX-based)
        - Night: after night_start OR before sunrise (motion-based)
        """
        # Build context from HA state (adapter side)
        context = self._build_mode_context()

        # Delegate to pure domain function
        mode = determine_mode(context)

        # Convert domain Mode to string constant
        mode_map = {
            Mode.DAY: MODE_DAY,
            Mode.NIGHT: MODE_NIGHT,
            Mode.SLEEP: MODE_SLEEP,
            Mode.WAKEUP: MODE_WAKEUP,
        }
        return mode_map[mode]

    def _get_sleep_start_time(self) -> dt_time:
        """Configured sleep mode start time."""
        return dt_time(*self._sleep_mode.start_time)

    def _get_sleep_end_time(self) -> dt_time:
        """Calculate sleep mode end time (Sleep Mode 2.0).

        Returns: sleep_start_time + sleep_duration_min

        Sleep Mode 2.0 requires explicit duration - no fallback to night_start.
        """
        duration_min = self._sleep_mode.duration_min

        if duration_min is None or duration_min <= 0:
            _LOGGER.error(
                "Sleep Mode 2.0: sleep_duration_min is required but not configured or invalid. "
                "Using 60 minutes as emergency fallback."
            )
            duration_min = 60  # Emergency fallback

        # Delegate to pure domain function
        sleep_start = self._get_sleep_start_time()
        return calculate_time_after(sleep_start, duration_min)

    def _get_wakeup_end_time(self) -> dt_time:
        """Configured wake-up completion time (when day mode begins)."""
        return dt_time(*self._wakeup_mode.wake_time)

    def _validate_config_edge_cases(self) -> None:
        """Validate configuration and log warnings for edge cases.

        Sleep Mode 2.0: Errors for missing duration or inverted configs without duration.
        """
        if self._sleep_mode.enabled:
            duration_min = self._sleep_mode.duration_min
            sleep_start = self._get_sleep_start_time()
            night_start = self._get_night_start_time()

            # Sleep Mode 2.0: Duration is REQUIRED
            if duration_min is None:
                _LOGGER.error(
                    "Sleep Mode 2.0: sleep_duration_min is REQUIRED but not configured. "
                    "Sleep mode will not work correctly. Please set a duration (15-240 minutes)."
                )

            # Check for inverted configuration without duration
            if sleep_start > night_start:
                if duration_min is None:
                    _LOGGER.error(
                        "Sleep Mode 2.0 ERROR: Inverted configuration detected "
                        "(sleep_start_time %s > night_mode_start_time %s) without explicit duration. "
                        "This configuration is NOT ALLOWED in Sleep Mode 2.0. "
                        "Please set sleep_duration_min to define the sleep window explicitly.",
                        sleep_start.strftime("%H:%M"),
                        night_start.strftime("%H:%M"),
                    )
                else:
                    _LOGGER.info(
                        "Sleep Mode 2.0: Inverted configuration (sleep_start %s > night_start %s) "
                        "with explicit duration %d min is OK.",
                        sleep_start.strftime("%H:%M"),
                        night_start.strftime("%H:%M"),
                        duration_min,
                    )

            # Check for very short sleep duration
            if duration_min is not None:
                if duration_min < 15:
                    _LOGGER.warning(
                        "Sleep duration is very short (%d min). "
                        "This may cause rapid brightness changes. "
                        "Consider using at least 15 minutes.",
                        duration_min,
                    )
                elif duration_min > 240:
                    _LOGGER.warning(
                        "Sleep duration is very long (%d min, %.1f hours). "
                        "Verify this is intentional.",
                        duration_min,
                        duration_min / 60,
                    )

        # Check for sleep/wake-up overlap
        if self._sleep_mode.enabled and self._wakeup_mode.enabled:
            sleep_end = self._get_sleep_end_time()
            wakeup_end = self._get_wakeup_end_time()
            wakeup_duration_min = self._wakeup_mode.duration_min

            # Calculate wake-up start time using domain function
            wakeup_start = calculate_time_before(wakeup_end, wakeup_duration_min)

            # Simple overlap check using domain function
            # This is informational only, not blocking
            if is_in_time_window(sleep_end, wakeup_start, wakeup_end):
                _LOGGER.info(
                    "Sleep mode (ends %s) and wake-up mode (starts %s) may overlap. "
                    "Sleep mode has priority and will activate first.",
                    sleep_end.strftime("%H:%M"),
                    wakeup_start.strftime("%H:%M"),
                )

    def calculate_progress_in_mode(self) -> float:
        """Calculate progress through the current mode's time window.

        Returns 0.0-1.0 progress for sleep/wake-up modes, 0.0 for day/night.

        This delegates to pure domain functions for calculations.
        """
        now = dt_util.now().time()
        mode = self.get_current_mode()

        if mode == MODE_SLEEP and self._sleep_mode.enabled:
            sleep_start = self._get_sleep_start_time()
            sleep_end = self._get_sleep_end_time()
            return calculate_progress_ratio(now, sleep_start, sleep_end)

        if mode == MODE_WAKEUP and self._wakeup_mode.enabled:
            wakeup_end = self._get_wakeup_end_time()
            wakeup_start = calculate_time_before(wakeup_end, self._wakeup_mode.duration_min)
            return calculate_progress_ratio(now, wakeup_start, wakeup_end)

        return 0.0
