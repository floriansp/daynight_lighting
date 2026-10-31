"""Unit tests for Wake-up Mode 2.0 (v1.5.0) - Independence from day/night mode.

Wake-up Mode 2.0 is an independent override mode that activates during its
configured time window regardless of sunrise or day/night state.

Priority order: Sleep Mode 2.0 > Wake-up Mode 2.0 > Day/Night Mode
"""

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from custom_components.daynight_lighting.const import (
    CONF_NIGHT_MODE_START,
    CONF_NIGHT_MODE_START_TIME,
    CONF_SLEEP_ENABLED,
    CONF_SLEEP_START_TIME,
    CONF_SLEEP_DURATION_MIN,
    CONF_WAKEUP_ENABLED,
    CONF_WAKEUP_TIME,
    CONF_WAKEUP_DURATION_MIN,
    MODE_DAY,
    MODE_NIGHT,
    MODE_SLEEP,
    MODE_WAKEUP,
)
from custom_components.daynight_lighting.schedule import DayNightSchedule
from custom_components.daynight_lighting.config import NightModeConfig, SleepModeConfig, WakeUpModeConfig


def _make_schedule(fake_hass, options: dict) -> DayNightSchedule:
    """Create DayNightSchedule from old-style options dict."""
    from custom_components.daynight_lighting.utils import parse_time_string

    # Parse night mode start time
    night_start_str = options.get(CONF_NIGHT_MODE_START_TIME, "22:00")
    night_start = parse_time_string(night_start_str, (22, 0))

    night_mode = NightModeConfig(
        start_time=night_start,
        start_trigger=options.get(CONF_NIGHT_MODE_START, "at_time"),
    )

    # Parse sleep config
    sleep_start_str = options.get(CONF_SLEEP_START_TIME, "21:00")
    sleep_start = parse_time_string(sleep_start_str, (21, 0))

    sleep_mode = SleepModeConfig(
        enabled=options.get(CONF_SLEEP_ENABLED, False),
        start_time=sleep_start,
        duration_min=options.get(CONF_SLEEP_DURATION_MIN, 60),
    )

    # Parse wake-up config
    wakeup_time_str = options.get(CONF_WAKEUP_TIME, "07:00")
    wakeup_time = parse_time_string(wakeup_time_str, (7, 0))

    wakeup_mode = WakeUpModeConfig(
        enabled=options.get(CONF_WAKEUP_ENABLED, False),
        wake_time=wakeup_time,
        duration_min=options.get(CONF_WAKEUP_DURATION_MIN, 30),
    )

    return DayNightSchedule(fake_hass, night_mode, sleep_mode, wakeup_mode)


def _make_sun_state(state: str, next_rising: str | None = None) -> MagicMock:
    """Create mock sun.sun state."""
    sun = MagicMock()
    sun.state = state
    if next_rising:
        sun.attributes = {"next_rising": next_rising}
    else:
        sun.attributes = {}
    return sun


@pytest.fixture
def fake_hass():
    """Fake Home Assistant instance."""
    hass = MagicMock()
    hass.states = MagicMock()
    return hass


class TestWakeupMode2Independence:
    """Tests for Wake-up Mode 2.0 independence from day/night mode."""

    def test_wakeup_during_sunrise_mid_window(self, fake_hass):
        """Wake-up 2.0: Sunrise occurs mid-window → wake-up continues.

        Configuration:
        - Wake-up: 06:30 - 07:00 (30 min)
        - Sunrise: 06:45 (mid-window)
        - Current time: 06:50

        Expected: MODE_WAKEUP (wake-up overrides day mode)
        """
        # Sun rises at 06:45, before wake-up ends
        fake_hass.states.set(
            "sun.sun",
            _make_sun_state("above_horizon", next_rising="2026-06-16T06:45:00+00:00"),
        )
        options = {
            CONF_NIGHT_MODE_START: "at_time",
            CONF_NIGHT_MODE_START_TIME: "22:00",
            CONF_WAKEUP_ENABLED: True,
            CONF_WAKEUP_TIME: "07:00",
            CONF_WAKEUP_DURATION_MIN: 30,  # 06:30 - 07:00
        }
        sched = _make_schedule(fake_hass, options)

        with patch("custom_components.daynight_lighting.schedule.dt_util") as mock_dt:
            # 06:50 - 10 minutes into wake-up, sun is up
            mock_dt.now.return_value = datetime(2026, 6, 15, 6, 50, 0)
            mock_dt.parse_datetime.return_value = datetime(2026, 6, 16, 6, 45, 0)
            mock_dt.as_local.side_effect = lambda x: x

            mode = sched.get_current_mode()
            assert mode == MODE_WAKEUP, (
                "Wake-up 2.0 should continue even after sunrise. "
                f"Expected MODE_WAKEUP, got {mode}"
            )

    def test_wakeup_with_sun_below_horizon_mode(self, fake_hass):
        """Wake-up 2.0: Works with sun_below_horizon night mode.

        Configuration:
        - night_mode_start: sun_below_horizon (day starts at sunrise)
        - Wake-up: 06:30 - 07:00
        - Sunrise: 06:40
        - Current time: 06:50

        Expected: MODE_WAKEUP (wake-up overrides day mode from sunrise)
        """
        # Sun rises at 06:40
        fake_hass.states.set(
            "sun.sun",
            _make_sun_state("above_horizon", next_rising="2026-06-16T06:40:00+00:00"),
        )
        options = {
            CONF_NIGHT_MODE_START: "sun_below_horizon",  # Day starts at sunrise
            CONF_WAKEUP_ENABLED: True,
            CONF_WAKEUP_TIME: "07:00",
            CONF_WAKEUP_DURATION_MIN: 30,
        }
        sched = _make_schedule(fake_hass, options)

        with patch("custom_components.daynight_lighting.schedule.dt_util") as mock_dt:
            # 06:50 - Sun is up (day mode would normally activate)
            mock_dt.now.return_value = datetime(2026, 6, 15, 6, 50, 0)
            mock_dt.parse_datetime.return_value = datetime(2026, 6, 16, 6, 40, 0)
            mock_dt.as_local.side_effect = lambda x: x

            mode = sched.get_current_mode()
            assert mode == MODE_WAKEUP, (
                "Wake-up 2.0 should work with sun_below_horizon mode. "
                f"Expected MODE_WAKEUP, got {mode}"
            )

    def test_wakeup_very_early_summer_sunrise(self, fake_hass):
        """Wake-up 2.0: Very early summer sunrise doesn't skip wake-up.

        Configuration:
        - Wake-up: 05:15 - 06:00 (45 min)
        - Sunrise: 05:30 (very early summer)
        - Current time: 05:45

        Expected: MODE_WAKEUP (wake-up continues despite early sunrise)
        """
        # Sun rises at 05:30
        fake_hass.states.set(
            "sun.sun",
            _make_sun_state("above_horizon", next_rising="2026-06-16T05:30:00+00:00"),
        )
        options = {
            CONF_NIGHT_MODE_START: "at_time",
            CONF_NIGHT_MODE_START_TIME: "22:00",
            CONF_WAKEUP_ENABLED: True,
            CONF_WAKEUP_TIME: "06:00",
            CONF_WAKEUP_DURATION_MIN: 45,  # 05:15 - 06:00
        }
        sched = _make_schedule(fake_hass, options)

        with patch("custom_components.daynight_lighting.schedule.dt_util") as mock_dt:
            # 05:45 - Mid wake-up, sun already up
            mock_dt.now.return_value = datetime(2026, 6, 15, 5, 45, 0)
            mock_dt.parse_datetime.return_value = datetime(2026, 6, 16, 5, 30, 0)
            mock_dt.as_local.side_effect = lambda x: x

            mode = sched.get_current_mode()
            assert mode == MODE_WAKEUP, (
                "Wake-up 2.0 should handle very early summer sunrise. "
                f"Expected MODE_WAKEUP, got {mode}"
            )

    def test_wakeup_crosses_midnight(self, fake_hass):
        """Wake-up 2.0: Handles midnight crossing correctly.

        Configuration:
        - Wake-up: 00:30 (end), 60 min duration → 23:30 - 00:30
        - Current time: 23:45 (before midnight)

        Expected: MODE_WAKEUP
        """
        fake_hass.states.set(
            "sun.sun",
            _make_sun_state("below_horizon", next_rising="2026-06-16T07:00:00+00:00"),
        )
        options = {
            CONF_NIGHT_MODE_START: "at_time",
            CONF_NIGHT_MODE_START_TIME: "22:00",
            CONF_WAKEUP_ENABLED: True,
            CONF_WAKEUP_TIME: "00:30",  # After midnight
            CONF_WAKEUP_DURATION_MIN: 60,  # 23:30 - 00:30
        }
        sched = _make_schedule(fake_hass, options)

        with patch("custom_components.daynight_lighting.schedule.dt_util") as mock_dt:
            # 23:45 - Before midnight, in wake-up window
            mock_dt.now.return_value = datetime(2026, 6, 15, 23, 45, 0)
            mock_dt.parse_datetime.return_value = datetime(2026, 6, 16, 7, 0, 0)
            mock_dt.as_local.side_effect = lambda x: x

            mode = sched.get_current_mode()
            assert mode == MODE_WAKEUP, (
                "Wake-up 2.0 should handle midnight crossing. "
                f"Expected MODE_WAKEUP at 23:45, got {mode}"
            )

    def test_wakeup_crosses_midnight_after_midnight(self, fake_hass):
        """Wake-up 2.0: Midnight crossing - after midnight in window.

        Configuration:
        - Wake-up: 00:30 (end), 60 min → 23:30 - 00:30
        - Current time: 00:15 (after midnight, still in window)

        Expected: MODE_WAKEUP
        """
        fake_hass.states.set(
            "sun.sun",
            _make_sun_state("below_horizon", next_rising="2026-06-16T07:00:00+00:00"),
        )
        options = {
            CONF_NIGHT_MODE_START: "at_time",
            CONF_NIGHT_MODE_START_TIME: "22:00",
            CONF_WAKEUP_ENABLED: True,
            CONF_WAKEUP_TIME: "00:30",
            CONF_WAKEUP_DURATION_MIN: 60,
        }
        sched = _make_schedule(fake_hass, options)

        with patch("custom_components.daynight_lighting.schedule.dt_util") as mock_dt:
            # 00:15 - After midnight, in wake-up window
            mock_dt.now.return_value = datetime(2026, 6, 16, 0, 15, 0)
            mock_dt.parse_datetime.return_value = datetime(2026, 6, 16, 7, 0, 0)
            mock_dt.as_local.side_effect = lambda x: x

            mode = sched.get_current_mode()
            assert mode == MODE_WAKEUP, (
                "Wake-up 2.0 should handle post-midnight window. "
                f"Expected MODE_WAKEUP at 00:15, got {mode}"
            )

    def test_wakeup_crosses_midnight_outside_window(self, fake_hass):
        """Wake-up 2.0: Midnight crossing - outside window after end.

        Configuration:
        - Wake-up: 00:30 (end), 60 min → 23:30 - 00:30
        - Current time: 00:45 (after window ends)

        Expected: MODE_NIGHT (wake-up ended)
        """
        fake_hass.states.set(
            "sun.sun",
            _make_sun_state("below_horizon", next_rising="2026-06-16T07:00:00+00:00"),
        )
        options = {
            CONF_NIGHT_MODE_START: "at_time",
            CONF_NIGHT_MODE_START_TIME: "22:00",
            CONF_WAKEUP_ENABLED: True,
            CONF_WAKEUP_TIME: "00:30",
            CONF_WAKEUP_DURATION_MIN: 60,
        }
        sched = _make_schedule(fake_hass, options)

        with patch("custom_components.daynight_lighting.schedule.dt_util") as mock_dt:
            # 00:45 - After wake-up ends at 00:30
            mock_dt.now.return_value = datetime(2026, 6, 16, 0, 45, 0)
            mock_dt.parse_datetime.return_value = datetime(2026, 6, 16, 7, 0, 0)
            mock_dt.as_local.side_effect = lambda x: x

            mode = sched.get_current_mode()
            assert mode == MODE_NIGHT, (
                "Wake-up 2.0 should end after window. "
                f"Expected MODE_NIGHT at 00:45, got {mode}"
            )

    def test_sleep_takes_priority_over_wakeup(self, fake_hass):
        """Sleep Mode 2.0 has higher priority than Wake-up 2.0.

        Configuration:
        - Sleep: 21:00 - 22:00 (60 min)
        - Wake-up: 21:30 - 22:00 (30 min) - overlaps with sleep
        - Current time: 21:30

        Expected: MODE_SLEEP (sleep has priority)
        """
        fake_hass.states.set(
            "sun.sun",
            _make_sun_state("below_horizon", next_rising="2026-06-16T07:00:00+00:00"),
        )
        options = {
            CONF_NIGHT_MODE_START: "at_time",
            CONF_NIGHT_MODE_START_TIME: "22:00",
            CONF_SLEEP_ENABLED: True,
            CONF_SLEEP_START_TIME: "21:00",
            CONF_SLEEP_DURATION_MIN: 60,  # 21:00 - 22:00
            CONF_WAKEUP_ENABLED: True,
            CONF_WAKEUP_TIME: "22:00",
            CONF_WAKEUP_DURATION_MIN: 30,  # 21:30 - 22:00 (overlaps)
        }
        sched = _make_schedule(fake_hass, options)

        with patch("custom_components.daynight_lighting.schedule.dt_util") as mock_dt:
            # 21:30 - Both sleep and wake-up windows active
            mock_dt.now.return_value = datetime(2026, 6, 15, 21, 30, 0)
            mock_dt.parse_datetime.return_value = datetime(2026, 6, 16, 7, 0, 0)
            mock_dt.as_local.side_effect = lambda x: x

            mode = sched.get_current_mode()
            assert mode == MODE_SLEEP, (
                "Sleep Mode 2.0 should take priority over Wake-up 2.0. "
                f"Expected MODE_SLEEP, got {mode}"
            )

    def test_wakeup_ends_transitions_to_day(self, fake_hass):
        """Wake-up 2.0: Window ends → transitions to day mode.

        Configuration:
        - Wake-up: 06:30 - 07:00
        - Sunrise: 06:45
        - Current time: 07:00 (wake-up just ended)

        Expected: MODE_DAY (wake-up ended, sun is up)
        """
        # Sun is up
        fake_hass.states.set(
            "sun.sun",
            _make_sun_state("above_horizon", next_rising="2026-06-16T06:45:00+00:00"),
        )
        options = {
            CONF_NIGHT_MODE_START: "at_time",
            CONF_NIGHT_MODE_START_TIME: "22:00",
            CONF_WAKEUP_ENABLED: True,
            CONF_WAKEUP_TIME: "07:00",
            CONF_WAKEUP_DURATION_MIN: 30,
        }
        sched = _make_schedule(fake_hass, options)

        with patch("custom_components.daynight_lighting.schedule.dt_util") as mock_dt:
            # 07:00 - Wake-up ends exactly now
            mock_dt.now.return_value = datetime(2026, 6, 15, 7, 0, 0)
            mock_dt.parse_datetime.return_value = datetime(2026, 6, 16, 6, 45, 0)
            mock_dt.as_local.side_effect = lambda x: x

            mode = sched.get_current_mode()
            assert mode == MODE_DAY, (
                "Wake-up 2.0 should transition to day mode when window ends. "
                f"Expected MODE_DAY, got {mode}"
            )

    def test_wakeup_before_window_returns_night(self, fake_hass):
        """Wake-up 2.0: Before window starts → night mode.

        Configuration:
        - Wake-up: 06:30 - 07:00
        - Current time: 06:00 (before window)

        Expected: MODE_NIGHT
        """
        fake_hass.states.set(
            "sun.sun",
            _make_sun_state("below_horizon", next_rising="2026-06-15T07:00:00+00:00"),
        )
        options = {
            CONF_NIGHT_MODE_START: "at_time",
            CONF_NIGHT_MODE_START_TIME: "22:00",
            CONF_WAKEUP_ENABLED: True,
            CONF_WAKEUP_TIME: "07:00",
            CONF_WAKEUP_DURATION_MIN: 30,
        }
        sched = _make_schedule(fake_hass, options)

        with patch("custom_components.daynight_lighting.schedule.dt_util") as mock_dt:
            # 06:00 - Before wake-up starts at 06:30
            mock_dt.now.return_value = datetime(2026, 6, 15, 6, 0, 0)
            mock_dt.parse_datetime.return_value = datetime(2026, 6, 15, 7, 0, 0)
            mock_dt.as_local.side_effect = lambda x: x

            mode = sched.get_current_mode()
            assert mode == MODE_NIGHT, (
                "Before wake-up window should be night mode. "
                f"Expected MODE_NIGHT, got {mode}"
            )

    def test_wakeup_disabled_sunrise_triggers_day(self, fake_hass):
        """Wake-up disabled → sunrise triggers day mode immediately.

        Configuration:
        - Wake-up: disabled
        - Sunrise: 06:45
        - Current time: 06:50

        Expected: MODE_DAY (no wake-up, sun is up)
        """
        # Sun is up
        fake_hass.states.set(
            "sun.sun",
            _make_sun_state("above_horizon", next_rising="2026-06-16T06:45:00+00:00"),
        )
        options = {
            CONF_NIGHT_MODE_START: "at_time",
            CONF_NIGHT_MODE_START_TIME: "22:00",
            CONF_WAKEUP_ENABLED: False,  # Disabled
        }
        sched = _make_schedule(fake_hass, options)

        with patch("custom_components.daynight_lighting.schedule.dt_util") as mock_dt:
            # 06:50 - Sun is up, no wake-up
            mock_dt.now.return_value = datetime(2026, 6, 15, 6, 50, 0)
            mock_dt.parse_datetime.return_value = datetime(2026, 6, 16, 6, 45, 0)
            mock_dt.as_local.side_effect = lambda x: x

            mode = sched.get_current_mode()
            assert mode == MODE_DAY, (
                "With wake-up disabled, sunrise should trigger day mode. "
                f"Expected MODE_DAY, got {mode}"
            )


class TestWakeupMode2EdgeCases:
    """Edge case tests for Wake-up Mode 2.0."""

    def test_full_mode_progression_with_wakeup(self, fake_hass):
        """Verify full day progression: night → wake-up → day → sleep → night.

        Wake-up 2.0 should integrate seamlessly into mode progression.
        """
        fake_hass.states.set(
            "sun.sun",
            _make_sun_state("below_horizon", next_rising="2026-06-15T07:00:00+00:00"),
        )
        options = {
            CONF_NIGHT_MODE_START: "at_time",
            CONF_NIGHT_MODE_START_TIME: "22:00",
            CONF_SLEEP_ENABLED: True,
            CONF_SLEEP_START_TIME: "21:00",
            CONF_SLEEP_DURATION_MIN: 60,
            CONF_WAKEUP_ENABLED: True,
            CONF_WAKEUP_TIME: "07:00",
            CONF_WAKEUP_DURATION_MIN: 30,
        }
        sched = _make_schedule(fake_hass, options)

        with patch("custom_components.daynight_lighting.schedule.dt_util") as mock_dt:
            # 03:00 - Night mode
            mock_dt.now.return_value = datetime(2026, 6, 15, 3, 0, 0)
            mock_dt.parse_datetime.return_value = datetime(2026, 6, 15, 7, 0, 0)
            mock_dt.as_local.side_effect = lambda x: x
            assert sched.get_current_mode() == MODE_NIGHT

            # 06:40 - Wake-up mode (20 min before 07:00)
            mock_dt.now.return_value = datetime(2026, 6, 15, 6, 40, 0)
            assert sched.get_current_mode() == MODE_WAKEUP

            # 12:00 - Day mode (wake-up ended, sun is up)
            fake_hass.states.set(
                "sun.sun",
                _make_sun_state("above_horizon", next_rising="2026-06-16T07:00:00+00:00"),
            )
            mock_dt.now.return_value = datetime(2026, 6, 15, 12, 0, 0)
            mock_dt.parse_datetime.return_value = datetime(2026, 6, 16, 7, 0, 0)
            assert sched.get_current_mode() == MODE_DAY

            # 21:30 - Sleep mode
            mock_dt.now.return_value = datetime(2026, 6, 15, 21, 30, 0)
            assert sched.get_current_mode() == MODE_SLEEP

            # 23:00 - Back to night
            fake_hass.states.set(
                "sun.sun",
                _make_sun_state("below_horizon", next_rising="2026-06-16T07:00:00+00:00"),
            )
            mock_dt.now.return_value = datetime(2026, 6, 15, 23, 0, 0)
            mock_dt.parse_datetime.return_value = datetime(2026, 6, 16, 7, 0, 0)
            assert sched.get_current_mode() == MODE_NIGHT

    def test_wakeup_and_sleep_both_independent(self, fake_hass):
        """Both Sleep 2.0 and Wake-up 2.0 are independent override modes.

        Verify they can coexist and don't interfere with each other.
        """
        fake_hass.states.set(
            "sun.sun",
            _make_sun_state("below_horizon", next_rising="2026-06-15T07:00:00+00:00"),
        )
        options = {
            CONF_NIGHT_MODE_START: "at_time",
            CONF_NIGHT_MODE_START_TIME: "22:00",
            CONF_SLEEP_ENABLED: True,
            CONF_SLEEP_START_TIME: "21:00",
            CONF_SLEEP_DURATION_MIN: 45,  # 21:00 - 21:45
            CONF_WAKEUP_ENABLED: True,
            CONF_WAKEUP_TIME: "07:00",
            CONF_WAKEUP_DURATION_MIN: 30,  # 06:30 - 07:00
        }
        sched = _make_schedule(fake_hass, options)

        with patch("custom_components.daynight_lighting.schedule.dt_util") as mock_dt:
            # 21:20 - In sleep window
            mock_dt.now.return_value = datetime(2026, 6, 15, 21, 20, 0)
            mock_dt.parse_datetime.return_value = datetime(2026, 6, 16, 7, 0, 0)
            mock_dt.as_local.side_effect = lambda x: x
            assert sched.get_current_mode() == MODE_SLEEP

            # 06:45 - In wake-up window
            mock_dt.now.return_value = datetime(2026, 6, 16, 6, 45, 0)
            assert sched.get_current_mode() == MODE_WAKEUP

            # Both modes work independently without interfering
