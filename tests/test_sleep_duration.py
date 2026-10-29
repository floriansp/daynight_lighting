"""Unit tests for sleep mode duration configuration (CONF_SLEEP_DURATION_MIN)."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import patch


from custom_components.daynight_lighting.schedule import DayNightSchedule
from custom_components.daynight_lighting.config import DayNightConfig
from custom_components.daynight_lighting.const import (
    CONF_NIGHT_MODE_START,
    CONF_NIGHT_MODE_START_TIME,
    CONF_SLEEP_ENABLED,
    CONF_SLEEP_START_TIME,
    CONF_SLEEP_DURATION_MIN,
    MODE_DAY,
    MODE_SLEEP,
    MODE_NIGHT,
)
from tests.conftest import FakeState


def _make_schedule(fake_hass, options):
    """Helper to create DayNightSchedule with proper config objects."""
    config = DayNightConfig.from_ha_options(options)
    return DayNightSchedule(
        fake_hass,
        night_mode=config.night_mode,
        sleep_mode=config.sleep_mode,
        wakeup_mode=config.wake_up_mode,
    )


def _make_sun_state(state="above_horizon", next_rising=None):
    """Helper to create sun.sun state."""
    attrs = {}
    if next_rising:
        attrs["next_rising"] = next_rising
    return FakeState(state=state, attributes=attrs)


class TestSleepDurationConfiguration:
    """Tests for explicit sleep_duration_min configuration."""

    def test_sleep_end_with_explicit_duration_60min(self, fake_hass):
        """sleep_duration_min=60 → end is start + 1 hour."""
        options = {
            CONF_SLEEP_ENABLED: True,
            CONF_SLEEP_START_TIME: "21:00",
            CONF_SLEEP_DURATION_MIN: 60,
            CONF_NIGHT_MODE_START_TIME: "23:00",  # Should be ignored
        }
        sched = _make_schedule(fake_hass, options)

        sleep_start = sched._get_sleep_start_time()
        sleep_end = sched._get_sleep_end_time()

        # Start: 21:00, Duration: 60 min → End: 22:00
        assert sleep_start.hour == 21
        assert sleep_start.minute == 0
        assert sleep_end.hour == 22
        assert sleep_end.minute == 0

    def test_sleep_end_with_explicit_duration_90min(self, fake_hass):
        """sleep_duration_min=90 → end is start + 1.5 hours."""
        options = {
            CONF_SLEEP_ENABLED: True,
            CONF_SLEEP_START_TIME: "20:30",
            CONF_SLEEP_DURATION_MIN: 90,
        }
        sched = _make_schedule(fake_hass, options)

        sleep_end = sched._get_sleep_end_time()

        # Start: 20:30, Duration: 90 min → End: 22:00
        assert sleep_end.hour == 22
        assert sleep_end.minute == 0


    def test_sleep_end_missing_duration_uses_emergency_fallback(self, fake_hass):
        """Sleep Mode 2.0: No duration key → emergency fallback to 60 minutes."""
        options = {
            CONF_SLEEP_ENABLED: True,
            CONF_SLEEP_START_TIME: "21:15",
            # No CONF_SLEEP_DURATION_MIN key - NOT ALLOWED
            CONF_NIGHT_MODE_START_TIME: "20:00",
        }
        sched = _make_schedule(fake_hass, options)

        sleep_end = sched._get_sleep_end_time()

        # Sleep Mode 2.0: Emergency fallback to 60 min (21:15 + 60 = 22:15)
        assert sleep_end.hour == 22
        assert sleep_end.minute == 15

    def test_sleep_duration_crosses_midnight(self, fake_hass):
        """Start: 23:30, Duration: 90 min → End: 01:00 (next day)."""
        options = {
            CONF_SLEEP_ENABLED: True,
            CONF_SLEEP_START_TIME: "23:30",
            CONF_SLEEP_DURATION_MIN: 90,
        }
        sched = _make_schedule(fake_hass, options)

        sleep_end = sched._get_sleep_end_time()

        # 23:30 + 90 min = 01:00 (next day)
        assert sleep_end.hour == 1
        assert sleep_end.minute == 0


class TestSleepModeWithExplicitDuration:
    """Tests for get_current_mode() using explicit sleep_duration_min."""

    def test_sleep_mode_active_with_60min_duration(self, fake_hass):
        """Sleep mode active: 21:00 start, 60 min duration, current time 21:30."""
        fake_hass.states.set("sun.sun", _make_sun_state("above_horizon"))
        options = {
            CONF_NIGHT_MODE_START: "at_time",
            CONF_NIGHT_MODE_START_TIME: "23:00",  # Night starts later
            CONF_SLEEP_ENABLED: True,
            CONF_SLEEP_START_TIME: "21:00",
            CONF_SLEEP_DURATION_MIN: 60,  # Sleep ends at 22:00
        }
        sched = _make_schedule(fake_hass, options)

        with patch("custom_components.daynight_lighting.schedule.dt_util") as mock_dt:
            # 21:30 - in sleep window (21:00 → 22:00)
            mock_dt.now.return_value = datetime(2026, 6, 15, 21, 30, 0)
            assert sched.get_current_mode() == MODE_SLEEP

    def test_day_mode_after_sleep_duration_ends(self, fake_hass):
        """After sleep duration ends, before night start → day mode."""
        fake_hass.states.set("sun.sun", _make_sun_state("above_horizon"))
        options = {
            CONF_NIGHT_MODE_START: "at_time",
            CONF_NIGHT_MODE_START_TIME: "23:00",
            CONF_SLEEP_ENABLED: True,
            CONF_SLEEP_START_TIME: "21:00",
            CONF_SLEEP_DURATION_MIN: 60,  # Sleep ends at 22:00
        }
        sched = _make_schedule(fake_hass, options)

        with patch("custom_components.daynight_lighting.schedule.dt_util") as mock_dt:
            # 22:30 - after sleep (22:00), before night (23:00) → day mode
            mock_dt.now.return_value = datetime(2026, 6, 15, 22, 30, 0)
            assert sched.get_current_mode() == MODE_DAY

    def test_sleep_mode_with_midnight_wrap(self, fake_hass):
        """Sleep crosses midnight: 23:00 start, 120 min → ends at 01:00."""
        fake_hass.states.set("sun.sun", _make_sun_state("above_horizon"))
        options = {
            CONF_NIGHT_MODE_START: "at_time",
            CONF_NIGHT_MODE_START_TIME: "22:00",  # Night already started
            CONF_SLEEP_ENABLED: True,
            CONF_SLEEP_START_TIME: "23:00",
            CONF_SLEEP_DURATION_MIN: 120,  # 2 hours → ends at 01:00
        }
        sched = _make_schedule(fake_hass, options)

        with patch("custom_components.daynight_lighting.schedule.dt_util") as mock_dt:
            # 23:30 - in sleep window (23:00 → 01:00)
            mock_dt.now.return_value = datetime(2026, 6, 15, 23, 30, 0)
            assert sched.get_current_mode() == MODE_SLEEP

            # 00:30 - still in sleep window (crosses midnight)
            mock_dt.now.return_value = datetime(2026, 6, 16, 0, 30, 0)
            assert sched.get_current_mode() == MODE_SLEEP

    def test_inverted_config_with_explicit_duration(self, fake_hass):
        """User's inverted case: night_start=20:00, sleep_start=21:15, duration=60."""
        fake_hass.states.set("sun.sun", _make_sun_state("above_horizon"))
        options = {
            CONF_NIGHT_MODE_START: "at_time",
            CONF_NIGHT_MODE_START_TIME: "20:00",  # Night starts early
            CONF_SLEEP_ENABLED: True,
            CONF_SLEEP_START_TIME: "21:15",
            CONF_SLEEP_DURATION_MIN: 60,  # Sleep ends at 22:15
        }
        sched = _make_schedule(fake_hass, options)

        with patch("custom_components.daynight_lighting.schedule.dt_util") as mock_dt:
            # 21:20 - in sleep window (21:15 → 22:15)
            mock_dt.now.return_value = datetime(2026, 6, 15, 21, 20, 0)
            assert sched.get_current_mode() == MODE_SLEEP

            # 20:30 - before sleep start → night mode (night started at 20:00)
            fake_hass.states.set(
                "sun.sun",
                _make_sun_state("below_horizon", next_rising="2026-06-16T07:00:00+00:00"),
            )
            mock_dt.now.return_value = datetime(2026, 6, 15, 20, 30, 0)
            mock_dt.parse_datetime.return_value = datetime(2026, 6, 16, 7, 0, 0)
            mock_dt.as_local.side_effect = lambda x: x
            assert sched.get_current_mode() == MODE_NIGHT

            # 22:20 - after sleep ends (22:15) → night mode
            mock_dt.now.return_value = datetime(2026, 6, 15, 22, 20, 0)
            assert sched.get_current_mode() == MODE_NIGHT


class TestBackwardCompatibility:
    """Tests to ensure backward compatibility when duration is not configured."""

    def test_no_duration_config_uses_emergency_fallback(self, fake_hass):
        """Sleep Mode 2.0: No duration configured → 60 min emergency fallback."""
        fake_hass.states.set("sun.sun", _make_sun_state("above_horizon"))
        options = {
            CONF_NIGHT_MODE_START: "at_time",
            CONF_NIGHT_MODE_START_TIME: "23:00",
            CONF_SLEEP_ENABLED: True,
            CONF_SLEEP_START_TIME: "21:00",
            # No CONF_SLEEP_DURATION_MIN - uses 60 min fallback
        }
        sched = _make_schedule(fake_hass, options)

        with patch("custom_components.daynight_lighting.schedule.dt_util") as mock_dt:
            # 21:30 - within 60 min emergency window (21:00 → 22:00)
            mock_dt.now.return_value = datetime(2026, 6, 15, 21, 30, 0)
            assert sched.get_current_mode() == MODE_SLEEP

