"""Pure domain tests for schedule and mode determination functions.

These tests verify the pure mathematical functions in domain/schedule.py
without any Home Assistant dependencies or side effects.
"""

from __future__ import annotations

from datetime import time as dt_time

import pytest

from custom_components.daynight_lighting.domain.models import Mode
from custom_components.daynight_lighting.domain.schedule import (
    time_to_minutes,
    is_in_time_window,
    calculate_progress_ratio,
    calculate_time_after,
    calculate_time_before,
    ModeDeterminationContext,
    determine_mode,
)


class TestTimeToMinutes:
    """Tests for time_to_minutes utility function."""

    def test_midnight(self):
        """Midnight converts to 0 minutes."""
        assert time_to_minutes(dt_time(0, 0)) == 0

    def test_noon(self):
        """Noon converts to 720 minutes (12 * 60)."""
        assert time_to_minutes(dt_time(12, 0)) == 720

    def test_with_minutes(self):
        """Time with minutes converts correctly."""
        assert time_to_minutes(dt_time(14, 30)) == 870  # 14*60 + 30 = 870
        assert time_to_minutes(dt_time(23, 59)) == 1439

    def test_edge_cases(self):
        """Edge cases work correctly."""
        assert time_to_minutes(dt_time(0, 1)) == 1
        assert time_to_minutes(dt_time(1, 0)) == 60
        assert time_to_minutes(dt_time(23, 0)) == 1380


class TestIsInTimeWindow:
    """Tests for is_in_time_window function."""

    def test_window_within_same_day(self):
        """Time window that doesn't cross midnight."""
        window_start = dt_time(12, 0)
        window_end = dt_time(16, 0)

        # Inside window
        assert is_in_time_window(dt_time(14, 0), window_start, window_end) is True
        assert is_in_time_window(dt_time(12, 0), window_start, window_end) is True  # Start inclusive
        assert is_in_time_window(dt_time(15, 59), window_start, window_end) is True

        # Outside window
        assert is_in_time_window(dt_time(11, 59), window_start, window_end) is False
        assert is_in_time_window(dt_time(16, 0), window_start, window_end) is False  # End exclusive
        assert is_in_time_window(dt_time(20, 0), window_start, window_end) is False

    def test_window_crossing_midnight(self):
        """Time window that crosses midnight (start > end)."""
        window_start = dt_time(22, 0)  # 10 PM
        window_end = dt_time(2, 0)     # 2 AM (next day)

        # Inside window (after start, before midnight)
        assert is_in_time_window(dt_time(23, 0), window_start, window_end) is True
        assert is_in_time_window(dt_time(22, 0), window_start, window_end) is True  # Start inclusive
        assert is_in_time_window(dt_time(0, 0), window_start, window_end) is True   # After midnight
        assert is_in_time_window(dt_time(1, 59), window_start, window_end) is True

        # Outside window
        assert is_in_time_window(dt_time(21, 59), window_start, window_end) is False
        assert is_in_time_window(dt_time(2, 0), window_start, window_end) is False   # End exclusive
        assert is_in_time_window(dt_time(3, 0), window_start, window_end) is False
        assert is_in_time_window(dt_time(14, 0), window_start, window_end) is False  # Daytime

    def test_window_whole_day(self):
        """Window from midnight to midnight (same time) is zero-length."""
        window_start = dt_time(0, 0)
        window_end = dt_time(0, 0)  # Same time = zero-length window

        # Zero-length window: start <= current < end, but start == end
        # So no time satisfies 0 <= current < 0
        assert is_in_time_window(dt_time(0, 0), window_start, window_end) is False
        assert is_in_time_window(dt_time(12, 0), window_start, window_end) is False
        assert is_in_time_window(dt_time(23, 59), window_start, window_end) is False

    def test_one_minute_window(self):
        """Very short time window."""
        window_start = dt_time(14, 30)
        window_end = dt_time(14, 31)  # One minute window

        assert is_in_time_window(dt_time(14, 30), window_start, window_end) is True
        assert is_in_time_window(dt_time(14, 30, 30), window_start, window_end) is True  # Microseconds
        assert is_in_time_window(dt_time(14, 31), window_start, window_end) is False  # End exclusive
        assert is_in_time_window(dt_time(14, 29), window_start, window_end) is False

    def test_reversed_normal_window(self):
        """When start < end but times suggest it's a normal window."""
        # This should work like normal window (not crossing midnight)
        window_start = dt_time(8, 0)
        window_end = dt_time(17, 0)

        assert is_in_time_window(dt_time(12, 0), window_start, window_end) is True
        assert is_in_time_window(dt_time(5, 0), window_start, window_end) is False


class TestCalculateProgressRatio:
    """Tests for calculate_progress_ratio function."""

    def test_progress_within_same_day_window(self):
        """Progress calculation for window within same day."""
        window_start = dt_time(12, 0)
        window_end = dt_time(16, 0)  # 4-hour window

        # At start
        assert calculate_progress_ratio(dt_time(12, 0), window_start, window_end) == 0.0

        # Quarter through (30 minutes into 4-hour window = 0.125)
        assert calculate_progress_ratio(dt_time(12, 30), window_start, window_end) == 0.125

        # Halfway through
        assert calculate_progress_ratio(dt_time(14, 0), window_start, window_end) == 0.5

        # Three quarters through
        assert calculate_progress_ratio(dt_time(15, 0), window_start, window_end) == 0.75

        # Near end (15:59, 3h59m into 4h = ~0.997)
        progress = calculate_progress_ratio(dt_time(15, 59), window_start, window_end)
        assert 0.99 < progress < 1.0

    def test_progress_crossing_midnight(self):
        """Progress calculation for window crossing midnight."""
        window_start = dt_time(22, 0)  # 10 PM
        window_end = dt_time(2, 0)     # 2 AM (4-hour window)

        # At start
        assert calculate_progress_ratio(dt_time(22, 0), window_start, window_end) == 0.0

        # 2 hours after start (midnight)
        assert calculate_progress_ratio(dt_time(0, 0), window_start, window_end) == 0.5

        # 3 hours after start (1 AM)
        assert calculate_progress_ratio(dt_time(1, 0), window_start, window_end) == 0.75

        # Just before end
        progress = calculate_progress_ratio(dt_time(1, 59), window_start, window_end)
        assert 0.99 < progress < 1.0

    def test_progress_before_window(self):
        """Progress before window start returns 0.0."""
        window_start = dt_time(10, 0)
        window_end = dt_time(12, 0)

        assert calculate_progress_ratio(dt_time(9, 0), window_start, window_end) == 0.0
        assert calculate_progress_ratio(dt_time(5, 30), window_start, window_end) == 0.0

    def test_progress_after_window(self):
        """Progress after window end returns 1.0."""
        window_start = dt_time(10, 0)
        window_end = dt_time(12, 0)

        assert calculate_progress_ratio(dt_time(12, 0), window_start, window_end) == 1.0
        assert calculate_progress_ratio(dt_time(14, 0), window_start, window_end) == 1.0
        assert calculate_progress_ratio(dt_time(23, 59), window_start, window_end) == 1.0

    def test_zero_duration_window(self):
        """Window with zero duration returns 1.0."""
        window_start = dt_time(10, 0)
        window_end = dt_time(10, 0)  # Zero duration

        assert calculate_progress_ratio(dt_time(10, 0), window_start, window_end) == 1.0
        assert calculate_progress_ratio(dt_time(9, 0), window_start, window_end) == 1.0
        assert calculate_progress_ratio(dt_time(11, 0), window_start, window_end) == 1.0

    def test_negative_progress_clamped(self):
        """Progress < 0.0 is clamped to 0.0."""
        window_start = dt_time(10, 0)
        window_end = dt_time(12, 0)

        # Current time before start (negative elapsed)
        assert calculate_progress_ratio(dt_time(9, 0), window_start, window_end) == 0.0

    def test_progress_greater_than_one_clamped(self):
        """Progress > 1.0 is clamped to 1.0."""
        window_start = dt_time(10, 0)
        window_end = dt_time(12, 0)

        assert calculate_progress_ratio(dt_time(13, 0), window_start, window_end) == 1.0


class TestCalculateTimeAfter:
    """Tests for calculate_time_after function."""

    def test_add_minutes_without_wrapping(self):
        """Adding minutes within same day."""
        start = dt_time(14, 30)

        # Add 30 minutes
        assert calculate_time_after(start, 30) == dt_time(15, 0)

        # Add 90 minutes (1.5 hours)
        assert calculate_time_after(start, 90) == dt_time(16, 0)

        # Add 0 minutes
        assert calculate_time_after(start, 0) == dt_time(14, 30)

    def test_add_minutes_with_wrapping(self):
        """Adding minutes that wraps past midnight."""
        # Wrap at midnight
        assert calculate_time_after(dt_time(23, 30), 60) == dt_time(0, 30)

        # Wrap multiple times (2.5 hours past 23:00)
        assert calculate_time_after(dt_time(23, 0), 150) == dt_time(1, 30)  # 23:00 + 2.5h = 01:30

        # Wrap exactly 24 hours
        assert calculate_time_after(dt_time(10, 0), 1440) == dt_time(10, 0)

        # Wrap more than 24 hours (25 hours)
        assert calculate_time_after(dt_time(10, 0), 1500) == dt_time(11, 0)  # 1440 + 60

    def test_edge_cases(self):
        """Edge cases for time addition."""
        # Midnight
        assert calculate_time_after(dt_time(0, 0), 30) == dt_time(0, 30)

        # One minute before midnight
        assert calculate_time_after(dt_time(23, 59), 1) == dt_time(0, 0)

        # Large duration
        assert calculate_time_after(dt_time(10, 0), 12345) == dt_time(23, 45)  # 12345 % 1440 = 825, 10:00 + 825min = 23:45

    def test_negative_duration_handled(self):
        """Negative durations should wrap correctly."""
        # Python modulo handles negative numbers: -60 % 1440 = 1380
        # 14:30 + (-60) = 14:30 - 60 = 13:30, but modulo gives 1380 = 23:00
        # This is expected behavior for the function
        result = calculate_time_after(dt_time(14, 30), -60)
        assert result == dt_time(13, 30)  # 14:30 - 1 hour = 13:30


class TestCalculateTimeBefore:
    """Tests for calculate_time_before function."""

    def test_subtract_minutes_without_wrapping(self):
        """Subtracting minutes within same day."""
        end = dt_time(15, 0)

        # Subtract 30 minutes
        assert calculate_time_before(end, 30) == dt_time(14, 30)

        # Subtract 90 minutes (1.5 hours)
        assert calculate_time_before(end, 90) == dt_time(13, 30)

        # Subtract 0 minutes
        assert calculate_time_before(end, 0) == dt_time(15, 0)

    def test_subtract_minutes_with_wrapping(self):
        """Subtracting minutes that wraps before midnight."""
        # Wrap before midnight
        assert calculate_time_before(dt_time(0, 30), 60) == dt_time(23, 30)

        # Wrap multiple times (2.5 hours before 1:30)
        assert calculate_time_before(dt_time(1, 30), 150) == dt_time(23, 0)  # 1:30 - 2.5h = 23:00

        # Wrap exactly 24 hours
        assert calculate_time_before(dt_time(10, 0), 1440) == dt_time(10, 0)

        # Wrap more than 24 hours (25 hours)
        assert calculate_time_before(dt_time(10, 0), 1500) == dt_time(9, 0)  # 1440 + 60

    def test_edge_cases(self):
        """Edge cases for time subtraction."""
        # Midnight
        assert calculate_time_before(dt_time(0, 0), 30) == dt_time(23, 30)

        # One minute after midnight
        assert calculate_time_before(dt_time(0, 1), 1) == dt_time(0, 0)

        # Large duration
        assert calculate_time_before(dt_time(10, 0), 12345) == dt_time(20, 15)  # 12345 % 1440 = 825, 10:00 - 825min = 20:15


class TestModeDeterminationContext:
    """Tests for ModeDeterminationContext dataclass."""

    def test_creation_with_minimal_fields(self):
        """Context can be created with only required fields."""
        ctx = ModeDeterminationContext(
            current_time=dt_time(14, 30),
        )

        assert ctx.current_time == dt_time(14, 30)
        assert ctx.sun_above_horizon is None
        assert ctx.sleep_enabled is False
        assert ctx.wakeup_enabled is False

    def test_creation_with_all_fields(self):
        """Context can be created with all optional fields."""
        ctx = ModeDeterminationContext(
            current_time=dt_time(22, 0),
            sun_above_horizon=False,
            next_sunrise_today=False,
            sleep_enabled=True,
            sleep_start_time=dt_time(21, 0),
            sleep_duration_min=60,
            wakeup_enabled=True,
            wakeup_time=dt_time(7, 0),
            wakeup_duration_min=30,
            night_start_time=dt_time(23, 0),
            night_start_trigger="at_time",
        )

        assert ctx.current_time == dt_time(22, 0)
        assert ctx.sun_above_horizon is False
        assert ctx.sleep_start_time == dt_time(21, 0)
        assert ctx.wakeup_time == dt_time(7, 0)
        assert ctx.night_start_time == dt_time(23, 0)
        assert ctx.night_start_trigger == "at_time"

    def test_immutability(self):
        """Context should be immutable (frozen dataclass)."""
        ctx = ModeDeterminationContext(current_time=dt_time(12, 0))

        with pytest.raises(Exception):
            ctx.current_time = dt_time(13, 0)  # Should raise


class TestDetermineMode:
    """Tests for determine_mode function."""

    def test_sleep_mode_priority(self):
        """Sleep mode takes priority over other modes when active."""
        ctx = ModeDeterminationContext(
            current_time=dt_time(21, 30),
            sun_above_horizon=False,  # Would be night mode
            sleep_enabled=True,
            sleep_start_time=dt_time(21, 0),
            sleep_duration_min=120,  # Until 23:00
            wakeup_enabled=True,
            wakeup_time=dt_time(7, 0),  # Would be wake-up if active
            wakeup_duration_min=30,
            night_start_time=dt_time(23, 0),
            night_start_trigger="at_time",
        )

        assert determine_mode(ctx) == Mode.SLEEP

    def test_wakeup_mode_priority(self):
        """Wake-up mode takes priority over day/night when active."""
        ctx = ModeDeterminationContext(
            current_time=dt_time(6, 45),
            sun_above_horizon=False,  # Would be night mode
            sleep_enabled=False,
            wakeup_enabled=True,
            wakeup_time=dt_time(7, 0),
            wakeup_duration_min=60,  # From 6:00 to 7:00
            night_start_time=dt_time(23, 0),
            night_start_trigger="at_time",
        )

        assert determine_mode(ctx) == Mode.WAKEUP

    def test_day_mode_sun_based(self):
        """Day mode when sun is above horizon (sun_based trigger)."""
        ctx = ModeDeterminationContext(
            current_time=dt_time(14, 0),
            sun_above_horizon=True,
            night_start_trigger="sun_below_horizon",
        )

        assert determine_mode(ctx) == Mode.DAY

    def test_night_mode_sun_based(self):
        """Night mode when sun is below horizon (sun_based trigger)."""
        ctx = ModeDeterminationContext(
            current_time=dt_time(23, 0),
            sun_above_horizon=False,
            night_start_trigger="sun_below_horizon",
        )

        assert determine_mode(ctx) == Mode.NIGHT

    def test_day_mode_at_time_before_night_start(self):
        """Day mode when using at_time trigger and before night_start."""
        ctx = ModeDeterminationContext(
            current_time=dt_time(20, 0),
            sun_above_horizon=True,  # Sun still up
            night_start_time=dt_time(22, 0),
            night_start_trigger="at_time",
        )

        assert determine_mode(ctx) == Mode.DAY

    def test_night_mode_at_time_after_night_start(self):
        """Night mode when using at_time trigger and after night_start."""
        ctx = ModeDeterminationContext(
            current_time=dt_time(23, 0),
            sun_above_horizon=False,
            night_start_time=dt_time(22, 0),
            night_start_trigger="at_time",
        )

        assert determine_mode(ctx) == Mode.NIGHT

    def test_morning_night_mode_at_time(self):
        """Before night_start but sun down and morning -> night mode."""
        ctx = ModeDeterminationContext(
            current_time=dt_time(5, 0),
            sun_above_horizon=False,
            next_sunrise_today=True,  # Sunrise today = morning
            night_start_time=dt_time(22, 0),
            night_start_trigger="at_time",
        )

        assert determine_mode(ctx) == Mode.NIGHT

    def test_evening_day_mode_at_time(self):
        """Before night_start, sun down, but evening -> day mode."""
        ctx = ModeDeterminationContext(
            current_time=dt_time(21, 0),
            sun_above_horizon=False,
            next_sunrise_today=False,  # Sunrise tomorrow = evening
            night_start_time=dt_time(22, 0),
            night_start_trigger="at_time",
        )

        assert determine_mode(ctx) == Mode.DAY

    def test_no_sun_data_fallback_to_day(self):
        """When sun data unavailable, fall back to day mode."""
        ctx = ModeDeterminationContext(
            current_time=dt_time(3, 0),
            sun_above_horizon=None,  # Unknown
            night_start_trigger="sun_below_horizon",
        )

        assert determine_mode(ctx) == Mode.DAY

    def test_sleep_disabled_skipped(self):
        """Sleep mode not active when disabled."""
        ctx = ModeDeterminationContext(
            current_time=dt_time(21, 30),
            sun_above_horizon=False,
            sleep_enabled=False,  # Disabled!
            sleep_start_time=dt_time(21, 0),
            sleep_duration_min=120,
            night_start_trigger="sun_below_horizon",
        )

        # Should be night mode, not sleep
        assert determine_mode(ctx) == Mode.NIGHT

    def test_wakeup_disabled_skipped(self):
        """Wake-up mode not active when disabled."""
        ctx = ModeDeterminationContext(
            current_time=dt_time(6, 45),
            sun_above_horizon=False,
            wakeup_enabled=False,  # Disabled!
            wakeup_time=dt_time(7, 0),
            wakeup_duration_min=60,
            night_start_trigger="sun_below_horizon",
        )

        # Should be night mode, not wake-up
        assert determine_mode(ctx) == Mode.NIGHT

    def test_no_night_start_time_fallback_sun_based(self):
        """When at_time trigger but no night_start_time, fallback to sun_based."""
        ctx = ModeDeterminationContext(
            current_time=dt_time(23, 0),
            sun_above_horizon=False,
            night_start_time=None,  # Missing!
            night_start_trigger="at_time",
        )

        # Should use sun-based logic
        assert determine_mode(ctx) == Mode.NIGHT

    def test_sleep_window_boundary_inclusive_start(self):
        """Sleep window includes start time."""
        ctx = ModeDeterminationContext(
            current_time=dt_time(21, 0),  # Exactly start time
            sleep_enabled=True,
            sleep_start_time=dt_time(21, 0),
            sleep_duration_min=60,
        )

        assert determine_mode(ctx) == Mode.SLEEP

    def test_sleep_window_boundary_exclusive_end(self):
        """Sleep window excludes end time."""
        ctx = ModeDeterminationContext(
            current_time=dt_time(22, 0),  # Exactly end time (21:00 + 60min)
            sleep_enabled=True,
            sleep_start_time=dt_time(21, 0),
            sleep_duration_min=60,
        )

        # Should NOT be sleep mode (end exclusive)
        assert determine_mode(ctx) != Mode.SLEEP

    def test_wakeup_window_boundary_inclusive_start(self):
        """Wake-up window includes start time."""
        # Wake-up from 6:30 to 7:00 (30 minutes)
        ctx = ModeDeterminationContext(
            current_time=dt_time(6, 30),  # Exactly start time
            wakeup_enabled=True,
            wakeup_time=dt_time(7, 0),
            wakeup_duration_min=30,
        )

        assert determine_mode(ctx) == Mode.WAKEUP

    def test_wakeup_window_boundary_exclusive_end(self):
        """Wake-up window excludes end time."""
        # Wake-up from 6:30 to 7:00 (30 minutes)
        ctx = ModeDeterminationContext(
            current_time=dt_time(7, 0),  # Exactly end time
            wakeup_enabled=True,
            wakeup_time=dt_time(7, 0),
            wakeup_duration_min=30,
        )

        # Should NOT be wake-up mode (end exclusive)
        assert determine_mode(ctx) != Mode.WAKEUP