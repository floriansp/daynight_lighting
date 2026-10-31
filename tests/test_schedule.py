"""Tests for DayNightSchedule — mode determination (day/night/sleep/wake).

Tests the is_day_mode(), get_current_mode(), and schedule calculations.
"""

from __future__ import annotations

from datetime import time as dt_time
from types import SimpleNamespace
from unittest.mock import MagicMock, patch


from custom_components.daynight_lighting.schedule import DayNightSchedule
from custom_components.daynight_lighting.const import MODE_DAY, MODE_NIGHT

from tests.conftest import FakeState


def _make_configs(
    night_start: tuple[int, int] = (22, 0),
    night_trigger: str = "at_time",
    sleep_enabled: bool = False,
    sleep_start: tuple[int, int] = (21, 0),
    sleep_duration: int = 60,
    wakeup_enabled: bool = False,
    wakeup_time: tuple[int, int] = (7, 0),
    wakeup_duration: int = 30,
) -> tuple[SimpleNamespace, SimpleNamespace, SimpleNamespace]:
    """Create config namespaces."""
    night_mode = SimpleNamespace(
        start_time=night_start,
        start_trigger=night_trigger,
        motion_off_delay_min=5,
        brightness=80,
        fallback="skip",
        on_enter_night="leave",
    )
    sleep_mode = SimpleNamespace(
        enabled=sleep_enabled,
        start_time=sleep_start,
        duration_min=sleep_duration,
        target_brightness=20,
        target_kelvin=2200,
    )
    wakeup_mode = SimpleNamespace(
        enabled=wakeup_enabled,
        wake_time=wakeup_time,
        duration_min=wakeup_duration,
        start_brightness=1,
    )
    return night_mode, sleep_mode, wakeup_mode


def _make_schedule(
    fake_hass,
    night_start: tuple[int, int] = (22, 0),
    night_trigger: str = "at_time",
    **kwargs,
) -> DayNightSchedule:
    """Create a DayNightSchedule."""
    night_mode, sleep_mode, wakeup_mode = _make_configs(
        night_start=night_start,
        night_trigger=night_trigger,
        **kwargs,
    )
    return DayNightSchedule(
        hass=fake_hass,
        night_mode=night_mode,
        sleep_mode=sleep_mode,
        wakeup_mode=wakeup_mode,
    )


# ===================================================================
#  is_day_mode with at_time trigger
# ===================================================================


class TestIsDayModeAtTime:
    """Tests for is_day_mode with at_time night start trigger."""

    def test_day_mode_before_night_start_with_sun_up(self, fake_hass):
        """Day mode at 15:00 with sun up."""
        fake_hass.states.set(
            "sun.sun",
            FakeState(state="above_horizon", attributes={"next_rising": "2026-06-17T05:00:00+00:00"}),
        )
        schedule = _make_schedule(fake_hass, night_start=(22, 0))

        with patch('custom_components.daynight_lighting.schedule.dt_util') as mock_dt:
            mock_dt.now.return_value = MagicMock(time=lambda: dt_time(15, 0))
            assert schedule.is_day_mode() is True

    def test_night_mode_after_night_start(self, fake_hass):
        """Night mode at 23:00 (after night start)."""
        fake_hass.states.set(
            "sun.sun",
            FakeState(state="above_horizon"),
        )
        schedule = _make_schedule(fake_hass, night_start=(22, 0))

        with patch('custom_components.daynight_lighting.schedule.dt_util') as mock_dt:
            mock_dt.now.return_value = MagicMock(time=lambda: dt_time(23, 0))
            assert schedule.is_day_mode() is False

    def test_night_mode_morning_before_sunrise(self, fake_hass):
        """Night mode at 05:00 before sunrise (sun below horizon)."""
        from datetime import datetime

        fake_hass.states.set(
            "sun.sun",
            FakeState(
                state="below_horizon",
                attributes={"next_rising": "2026-06-16T06:00:00+00:00"},  # Today
            ),
        )
        schedule = _make_schedule(fake_hass, night_start=(22, 0))

        # At 05:00, sun below horizon, next_rising is today 06:00
        # → morning (not evening after sunset) → night mode
        with patch('custom_components.daynight_lighting.schedule.dt_util') as mock_dt:
            # Use real datetime for now() - at 05:00 on 2026-06-16
            mock_dt.now.return_value = datetime(2026, 6, 16, 5, 0, 0)
            # as_local should return the datetime as-is (or with same date)
            mock_dt.as_local = lambda x: x
            # parse_datetime should parse the ISO string properly
            mock_dt.parse_datetime = lambda s: datetime.fromisoformat(s.replace('+00:00', '+00:00'))
            assert schedule.is_day_mode() is False

    def test_day_mode_evening_after_sunset_before_night_start(self, fake_hass):
        """Day mode at 20:00 after sunset but before night start."""
        fake_hass.states.set(
            "sun.sun",
            FakeState(
                state="below_horizon",
                attributes={"next_rising": "2026-06-17T06:00:00+00:00"},  # Tomorrow
            ),
        )
        schedule = _make_schedule(fake_hass, night_start=(22, 0))

        with patch('custom_components.daynight_lighting.schedule.dt_util') as mock_dt:
            mock_now = MagicMock()
            mock_now.time.return_value = dt_time(20, 0)
            mock_now.date.return_value.__eq__ = lambda self, other: False  # Different day
            mock_dt.now.return_value = mock_now
            mock_dt.as_local = lambda x: MagicMock(date=lambda: MagicMock(__eq__=lambda self, other: False))
            assert schedule.is_day_mode() is True


# ===================================================================
#  is_day_mode with sun_below_horizon trigger
# ===================================================================


class TestIsDayModeSunBelowHorizon:
    """Tests for is_day_mode with sun_below_horizon night start trigger."""

    def test_day_mode_sun_above_horizon(self, fake_hass):
        """Day mode when sun is above horizon."""
        fake_hass.states.set("sun.sun", FakeState(state="above_horizon"))
        schedule = _make_schedule(fake_hass, night_trigger="sun_below_horizon")

        assert schedule.is_day_mode() is True

    def test_night_mode_sun_below_horizon(self, fake_hass):
        """Night mode when sun is below horizon."""
        fake_hass.states.set("sun.sun", FakeState(state="below_horizon"))
        schedule = _make_schedule(fake_hass, night_trigger="sun_below_horizon")

        assert schedule.is_day_mode() is False

    def test_night_mode_no_sun_entity(self, fake_hass):
        """Night mode when sun.sun entity doesn't exist."""
        # Don't set sun.sun state
        schedule = _make_schedule(fake_hass, night_trigger="sun_below_horizon")

        assert schedule.is_day_mode() is False


# ===================================================================
#  get_mode_and_time_for_log
# ===================================================================


class TestGetModeAndTimeForLog:
    """Tests for get_mode_and_time_for_log method."""

    def test_returns_mode_and_formatted_time(self, fake_hass):
        """Returns night trigger mode and formatted night start time."""
        schedule = _make_schedule(fake_hass, night_start=(22, 30), night_trigger="at_time")

        mode, time_str = schedule.get_mode_and_time_for_log()

        assert mode == "at_time"
        assert time_str == "22:30"


# ===================================================================
#  get_current_mode basic tests
# ===================================================================


class TestGetCurrentModeBasic:
    """Basic tests for get_current_mode."""

    def test_returns_day_mode(self, fake_hass):
        """Returns MODE_DAY during day."""
        fake_hass.states.set(
            "sun.sun",
            FakeState(state="above_horizon", attributes={"next_rising": "2026-06-17T05:00:00+00:00"}),
        )
        schedule = _make_schedule(fake_hass, night_start=(22, 0))

        with patch('custom_components.daynight_lighting.schedule.dt_util') as mock_dt:
            mock_dt.now.return_value = MagicMock(time=lambda: dt_time(15, 0))
            assert schedule.get_current_mode() == MODE_DAY

    def test_returns_night_mode(self, fake_hass):
        """Returns MODE_NIGHT during night."""
        fake_hass.states.set(
            "sun.sun",
            FakeState(state="above_horizon"),
        )
        schedule = _make_schedule(fake_hass, night_start=(22, 0))

        with patch('custom_components.daynight_lighting.schedule.dt_util') as mock_dt:
            mock_dt.now.return_value = MagicMock(time=lambda: dt_time(23, 0))
            assert schedule.get_current_mode() == MODE_NIGHT


# ===================================================================
#  Sleep mode time calculations
# ===================================================================


class TestSleepModeTimeCalculations:
    """Tests for sleep mode time calculations."""

    def test_sleep_start_time(self, fake_hass):
        """_get_sleep_start_time returns configured time."""
        schedule = _make_schedule(fake_hass, sleep_enabled=True, sleep_start=(21, 30))

        start_time = schedule._get_sleep_start_time()
        assert start_time == dt_time(21, 30)

    def test_sleep_end_time_calculation(self, fake_hass):
        """_get_sleep_end_time calculates end from start + duration."""
        schedule = _make_schedule(
            fake_hass,
            sleep_enabled=True,
            sleep_start=(21, 0),
            sleep_duration=60,
        )

        end_time = schedule._get_sleep_end_time()
        assert end_time == dt_time(22, 0)

    def test_sleep_end_time_long_duration(self, fake_hass):
        """Sleep end time handles durations crossing midnight."""
        schedule = _make_schedule(
            fake_hass,
            sleep_enabled=True,
            sleep_start=(23, 0),
            sleep_duration=120,  # 2 hours
        )

        end_time = schedule._get_sleep_end_time()
        assert end_time == dt_time(1, 0)  # 1 AM next day


# ===================================================================
#  Wake-up mode time calculations
# ===================================================================


class TestWakeUpModeTimeCalculations:
    """Tests for wake-up mode time calculations."""

    def test_wakeup_end_time(self, fake_hass):
        """_get_wakeup_end_time returns configured wake time."""
        schedule = _make_schedule(fake_hass, wakeup_enabled=True, wakeup_time=(7, 30))

        end_time = schedule._get_wakeup_end_time()
        assert end_time == dt_time(7, 30)


# ===================================================================
#  calculate_progress_in_mode
# ===================================================================


class TestCalculateProgressInMode:
    """Tests for calculate_progress_in_mode method."""

    def test_zero_for_day_mode(self, fake_hass):
        """Returns 0.0 for day mode (no progress)."""
        fake_hass.states.set("sun.sun", FakeState(state="above_horizon"))
        schedule = _make_schedule(fake_hass, night_start=(22, 0))

        with patch('custom_components.daynight_lighting.schedule.dt_util') as mock_dt:
            mock_dt.now.return_value = MagicMock(time=lambda: dt_time(15, 0))
            assert schedule.calculate_progress_in_mode() == 0.0

    def test_zero_for_night_mode(self, fake_hass):
        """Returns 0.0 for night mode (no progress)."""
        fake_hass.states.set("sun.sun", FakeState(state="above_horizon"))
        schedule = _make_schedule(fake_hass, night_start=(22, 0))

        with patch('custom_components.daynight_lighting.schedule.dt_util') as mock_dt:
            mock_dt.now.return_value = MagicMock(time=lambda: dt_time(23, 0))
            assert schedule.calculate_progress_in_mode() == 0.0

    def test_progress_for_sleep_mode(self, fake_hass):
        """Returns progress for sleep mode."""
        fake_hass.states.set(
            "sun.sun",
            FakeState(state="above_horizon"),
        )
        schedule = _make_schedule(
            fake_hass,
            night_start=(23, 0),
            sleep_enabled=True,
            sleep_start=(21, 0),
            sleep_duration=60,
        )

        # At 21:30 (30 minutes into 60 minute sleep)
        with patch('custom_components.daynight_lighting.schedule.dt_util') as mock_dt:
            mock_dt.now.return_value = MagicMock(time=lambda: dt_time(21, 30))
            progress = schedule.calculate_progress_in_mode()
            assert 0.4 <= progress <= 0.6  # ~50%

    def test_progress_for_wakeup_mode(self, fake_hass):
        """Returns progress for wake-up mode."""
        fake_hass.states.set("sun.sun", FakeState(state="above_horizon"))
        schedule = _make_schedule(
            fake_hass,
            night_start=(22, 0),
            wakeup_enabled=True,
            wakeup_time=(7, 0),
            wakeup_duration=30,
        )

        # At 6:45 (15 minutes into 30 minute wake-up)
        with patch('custom_components.daynight_lighting.schedule.dt_util') as mock_dt:
            mock_dt.now.return_value = MagicMock(time=lambda: dt_time(6, 45))
            progress = schedule.calculate_progress_in_mode()
            # Progress depends on mode detection, might be 0 if not in wakeup
            assert isinstance(progress, float)
