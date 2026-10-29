"""Tests for domain/schedule.py - pure schedule and time calculation functions.

These tests verify time window calculations and mode determination without
any Home Assistant dependencies.
"""

from __future__ import annotations

from datetime import time as dt_time


from custom_components.daynight_lighting.domain.schedule import (
    time_to_minutes,
    is_in_time_window,
    calculate_progress_ratio,
    calculate_time_after,
    calculate_time_before,
    ModeDeterminationContext,
    determine_mode,
)
from custom_components.daynight_lighting.domain.models import Mode


# ===================================================================
#  time_to_minutes
# ===================================================================


class TestTimeToMinutes:
    """Tests for time_to_minutes function."""

    def test_midnight_is_zero(self):
        """Midnight (00:00) is 0 minutes."""
        assert time_to_minutes(dt_time(0, 0)) == 0

    def test_one_minute_past_midnight(self):
        """00:01 is 1 minute."""
        assert time_to_minutes(dt_time(0, 1)) == 1

    def test_one_am(self):
        """01:00 is 60 minutes."""
        assert time_to_minutes(dt_time(1, 0)) == 60

    def test_noon(self):
        """12:00 is 720 minutes."""
        assert time_to_minutes(dt_time(12, 0)) == 720

    def test_one_pm(self):
        """13:00 is 780 minutes."""
        assert time_to_minutes(dt_time(13, 0)) == 780

    def test_eleven_pm(self):
        """23:00 is 1380 minutes."""
        assert time_to_minutes(dt_time(23, 0)) == 1380

    def test_last_minute_of_day(self):
        """23:59 is 1439 minutes."""
        assert time_to_minutes(dt_time(23, 59)) == 1439

    def test_arbitrary_time(self):
        """Arbitrary time converts correctly."""
        # 14:35 = 14*60 + 35 = 840 + 35 = 875
        assert time_to_minutes(dt_time(14, 35)) == 875


# ===================================================================
#  is_in_time_window
# ===================================================================


class TestIsInTimeWindow:
    """Tests for is_in_time_window function."""

    # --- Normal windows (same day) ---

    def test_time_inside_window(self):
        """Time inside window returns True."""
        assert is_in_time_window(
            dt_time(14, 0),
            dt_time(12, 0),
            dt_time(16, 0),
        ) is True

    def test_time_before_window(self):
        """Time before window returns False."""
        assert is_in_time_window(
            dt_time(10, 0),
            dt_time(12, 0),
            dt_time(16, 0),
        ) is False

    def test_time_after_window(self):
        """Time after window returns False."""
        assert is_in_time_window(
            dt_time(18, 0),
            dt_time(12, 0),
            dt_time(16, 0),
        ) is False

    def test_time_at_window_start(self):
        """Time at window start is considered inside (inclusive start)."""
        assert is_in_time_window(
            dt_time(12, 0),
            dt_time(12, 0),
            dt_time(16, 0),
        ) is True

    def test_time_at_window_end(self):
        """Time at window end is considered outside (exclusive end)."""
        assert is_in_time_window(
            dt_time(16, 0),
            dt_time(12, 0),
            dt_time(16, 0),
        ) is False

    # --- Windows crossing midnight ---

    def test_crossing_midnight_inside_before_midnight(self):
        """Time inside crossing-midnight window (before midnight)."""
        # Window 23:00 - 01:00
        assert is_in_time_window(
            dt_time(23, 30),
            dt_time(23, 0),
            dt_time(1, 0),
        ) is True

    def test_crossing_midnight_inside_after_midnight(self):
        """Time inside crossing-midnight window (after midnight)."""
        # Window 23:00 - 01:00
        assert is_in_time_window(
            dt_time(0, 30),
            dt_time(23, 0),
            dt_time(1, 0),
        ) is True

    def test_crossing_midnight_outside_before_window(self):
        """Time outside crossing-midnight window (before window starts)."""
        # Window 23:00 - 01:00
        assert is_in_time_window(
            dt_time(22, 0),
            dt_time(23, 0),
            dt_time(1, 0),
        ) is False

    def test_crossing_midnight_outside_after_window(self):
        """Time outside crossing-midnight window (after window ends)."""
        # Window 23:00 - 01:00
        assert is_in_time_window(
            dt_time(2, 0),
            dt_time(23, 0),
            dt_time(1, 0),
        ) is False

    def test_crossing_midnight_at_start(self):
        """Time at crossing-midnight window start (inclusive)."""
        assert is_in_time_window(
            dt_time(23, 0),
            dt_time(23, 0),
            dt_time(1, 0),
        ) is True

    def test_crossing_midnight_at_end(self):
        """Time at crossing-midnight window end (exclusive)."""
        assert is_in_time_window(
            dt_time(1, 0),
            dt_time(23, 0),
            dt_time(1, 0),
        ) is False

    # --- Edge cases ---

    def test_one_minute_window(self):
        """One-minute window works correctly."""
        assert is_in_time_window(
            dt_time(12, 0),
            dt_time(12, 0),
            dt_time(12, 1),
        ) is True
        assert is_in_time_window(
            dt_time(12, 1),
            dt_time(12, 0),
            dt_time(12, 1),
        ) is False


# ===================================================================
#  calculate_progress_ratio
# ===================================================================


class TestCalculateProgressRatio:
    """Tests for calculate_progress_ratio function."""

    # --- Normal windows ---

    def test_progress_at_start(self):
        """At window start, progress is 0.0."""
        assert calculate_progress_ratio(
            dt_time(12, 0),
            dt_time(12, 0),
            dt_time(16, 0),
        ) == 0.0

    def test_progress_at_end(self):
        """At window end, progress is 1.0."""
        assert calculate_progress_ratio(
            dt_time(16, 0),
            dt_time(12, 0),
            dt_time(16, 0),
        ) == 1.0

    def test_progress_at_midpoint(self):
        """At window midpoint, progress is 0.5."""
        assert calculate_progress_ratio(
            dt_time(14, 0),
            dt_time(12, 0),
            dt_time(16, 0),
        ) == 0.5

    def test_progress_quarter_way(self):
        """At quarter of window, progress is 0.25."""
        # 1-hour window, 15 minutes in
        assert calculate_progress_ratio(
            dt_time(12, 15),
            dt_time(12, 0),
            dt_time(13, 0),
        ) == 0.25

    def test_progress_three_quarters(self):
        """At three quarters of window, progress is 0.75."""
        # 1-hour window, 45 minutes in
        assert calculate_progress_ratio(
            dt_time(12, 45),
            dt_time(12, 0),
            dt_time(13, 0),
        ) == 0.75

    # --- Crossing midnight windows ---

    def test_progress_crossing_midnight_at_start(self):
        """At crossing-midnight window start, progress is 0.0."""
        assert calculate_progress_ratio(
            dt_time(23, 0),
            dt_time(23, 0),
            dt_time(1, 0),
        ) == 0.0

    def test_progress_crossing_midnight_near_end(self):
        """Near crossing-midnight window end, progress is close to 1.0."""
        # Window 23:00-01:00, at 00:59 (1 minute before end)
        result = calculate_progress_ratio(
            dt_time(0, 59),
            dt_time(23, 0),
            dt_time(1, 0),
        )
        # 2 hour window = 120 min, at 119 min = ~0.99 progress
        assert result > 0.99

    def test_progress_crossing_midnight_halfway(self):
        """Halfway through crossing-midnight window."""
        # Window 23:00-01:00 is 2 hours
        # At 00:00, we're 1 hour in = 0.5 progress
        assert calculate_progress_ratio(
            dt_time(0, 0),
            dt_time(23, 0),
            dt_time(1, 0),
        ) == 0.5

    def test_progress_crossing_midnight_quarter(self):
        """Quarter through crossing-midnight window."""
        # Window 23:00-01:00 is 2 hours
        # At 23:30, we're 30 min in = 0.25 progress
        assert calculate_progress_ratio(
            dt_time(23, 30),
            dt_time(23, 0),
            dt_time(1, 0),
        ) == 0.25

    # --- Out of bounds ---

    def test_progress_before_window_clamped_to_zero(self):
        """Time before window is clamped to 0.0."""
        assert calculate_progress_ratio(
            dt_time(10, 0),
            dt_time(12, 0),
            dt_time(16, 0),
        ) == 0.0

    def test_progress_after_window_clamped_to_one(self):
        """Time after window is clamped to 1.0."""
        assert calculate_progress_ratio(
            dt_time(18, 0),
            dt_time(12, 0),
            dt_time(16, 0),
        ) == 1.0


# ===================================================================
#  calculate_time_after
# ===================================================================


class TestCalculateTimeAfter:
    """Tests for calculate_time_after function."""

    def test_add_zero_minutes(self):
        """Adding 0 minutes returns same time."""
        assert calculate_time_after(dt_time(12, 0), 0) == dt_time(12, 0)

    def test_add_one_hour(self):
        """Adding 60 minutes advances by 1 hour."""
        assert calculate_time_after(dt_time(10, 0), 60) == dt_time(11, 0)

    def test_add_minutes_within_hour(self):
        """Adding minutes within same hour."""
        assert calculate_time_after(dt_time(10, 30), 20) == dt_time(10, 50)

    def test_add_crossing_hour(self):
        """Adding minutes that cross hour boundary."""
        assert calculate_time_after(dt_time(10, 45), 30) == dt_time(11, 15)

    def test_add_crossing_midnight(self):
        """Adding duration that crosses midnight wraps correctly."""
        # 23:30 + 60 = 00:30
        assert calculate_time_after(dt_time(23, 30), 60) == dt_time(0, 30)

    def test_add_exactly_24_hours(self):
        """Adding 1440 minutes (24 hours) returns same time."""
        assert calculate_time_after(dt_time(12, 0), 1440) == dt_time(12, 0)

    def test_add_multiple_hours(self):
        """Adding multiple hours."""
        assert calculate_time_after(dt_time(22, 0), 120) == dt_time(0, 0)

    def test_add_large_duration(self):
        """Adding large duration wraps correctly."""
        # 20:00 + 600 min (10h) = 06:00 next day
        assert calculate_time_after(dt_time(20, 0), 600) == dt_time(6, 0)


# ===================================================================
#  calculate_time_before
# ===================================================================


class TestCalculateTimeBefore:
    """Tests for calculate_time_before function."""

    def test_subtract_zero_minutes(self):
        """Subtracting 0 minutes returns same time."""
        assert calculate_time_before(dt_time(12, 0), 0) == dt_time(12, 0)

    def test_subtract_one_hour(self):
        """Subtracting 60 minutes goes back 1 hour."""
        assert calculate_time_before(dt_time(11, 0), 60) == dt_time(10, 0)

    def test_subtract_minutes_within_hour(self):
        """Subtracting minutes within same hour."""
        assert calculate_time_before(dt_time(10, 50), 20) == dt_time(10, 30)

    def test_subtract_crossing_hour(self):
        """Subtracting duration that crosses hour boundary."""
        assert calculate_time_before(dt_time(11, 15), 30) == dt_time(10, 45)

    def test_subtract_crossing_midnight(self):
        """Subtracting duration that crosses midnight wraps correctly."""
        # 01:00 - 120 = 23:00 (previous day)
        assert calculate_time_before(dt_time(1, 0), 120) == dt_time(23, 0)

    def test_subtract_exactly_24_hours(self):
        """Subtracting 1440 minutes (24 hours) returns same time."""
        assert calculate_time_before(dt_time(12, 0), 1440) == dt_time(12, 0)

    def test_subtract_large_duration(self):
        """Subtracting large duration wraps correctly."""
        # 06:00 - 600 min (10h) = 20:00 previous day
        assert calculate_time_before(dt_time(6, 0), 600) == dt_time(20, 0)


# ===================================================================
#  determine_mode
# ===================================================================


class TestDetermineMode:
    """Tests for determine_mode function."""

    # --- Day mode ---

    def test_day_mode_when_sun_above_horizon(self):
        """Sun above horizon returns DAY mode."""
        ctx = ModeDeterminationContext(
            current_time=dt_time(14, 0),
            sun_above_horizon=True,
        )
        assert determine_mode(ctx) == Mode.DAY

    # --- Night mode ---

    def test_night_mode_when_sun_below_horizon(self):
        """Sun below horizon returns NIGHT mode."""
        ctx = ModeDeterminationContext(
            current_time=dt_time(23, 0),
            sun_above_horizon=False,
        )
        assert determine_mode(ctx) == Mode.NIGHT

    def test_night_mode_default_sun_below_horizon(self):
        """Default trigger is sun_below_horizon."""
        ctx = ModeDeterminationContext(
            current_time=dt_time(2, 0),
            sun_above_horizon=False,
        )
        assert determine_mode(ctx) == Mode.NIGHT

    # --- Sleep mode (priority 1) ---

    def test_sleep_mode_takes_priority(self):
        """Sleep mode takes priority over day/night."""
        ctx = ModeDeterminationContext(
            current_time=dt_time(21, 30),  # In sleep window
            sun_above_horizon=False,
            sleep_enabled=True,
            sleep_start_time=dt_time(21, 0),
            sleep_duration_min=60,
        )
        assert determine_mode(ctx) == Mode.SLEEP

    def test_sleep_mode_not_active_outside_window(self):
        """Sleep mode not active outside sleep window."""
        ctx = ModeDeterminationContext(
            current_time=dt_time(20, 0),  # Before sleep window
            sun_above_horizon=True,
            sleep_enabled=True,
            sleep_start_time=dt_time(21, 0),
            sleep_duration_min=60,
        )
        assert determine_mode(ctx) == Mode.DAY

    def test_sleep_mode_disabled(self):
        """Sleep mode disabled means never in sleep mode."""
        ctx = ModeDeterminationContext(
            current_time=dt_time(21, 30),
            sun_above_horizon=False,
            sleep_enabled=False,
            sleep_start_time=dt_time(21, 0),
            sleep_duration_min=60,
        )
        assert determine_mode(ctx) == Mode.NIGHT

    def test_sleep_mode_crossing_midnight(self):
        """Sleep mode window crossing midnight works."""
        # Sleep 23:30-01:00, current time 00:30
        ctx = ModeDeterminationContext(
            current_time=dt_time(0, 30),
            sun_above_horizon=False,
            sleep_enabled=True,
            sleep_start_time=dt_time(23, 30),
            sleep_duration_min=90,
        )
        assert determine_mode(ctx) == Mode.SLEEP

    # --- Wake-up mode (priority 2) ---

    def test_wakeup_mode_takes_priority_over_night(self):
        """Wake-up mode takes priority over night mode."""
        # Wake-up 06:30-07:00, current 06:45
        ctx = ModeDeterminationContext(
            current_time=dt_time(6, 45),
            sun_above_horizon=False,
            wakeup_enabled=True,
            wakeup_time=dt_time(7, 0),
            wakeup_duration_min=30,
        )
        assert determine_mode(ctx) == Mode.WAKEUP

    def test_wakeup_mode_not_active_outside_window(self):
        """Wake-up mode not active outside wake-up window."""
        # Wake-up 06:30-07:00, current 08:00 (after)
        ctx = ModeDeterminationContext(
            current_time=dt_time(8, 0),
            sun_above_horizon=True,
            wakeup_enabled=True,
            wakeup_time=dt_time(7, 0),
            wakeup_duration_min=30,
        )
        assert determine_mode(ctx) == Mode.DAY

    def test_wakeup_mode_disabled(self):
        """Wake-up mode disabled means never in wake-up mode."""
        ctx = ModeDeterminationContext(
            current_time=dt_time(6, 45),
            sun_above_horizon=False,
            wakeup_enabled=False,
            wakeup_time=dt_time(7, 0),
            wakeup_duration_min=30,
        )
        assert determine_mode(ctx) == Mode.NIGHT

    # --- Sleep takes priority over Wake-up ---

    def test_sleep_priority_over_wakeup(self):
        """Sleep mode takes priority over wake-up when both active."""
        # Sleep 21:00-22:00, Wake-up 06:30-07:00
        # At 21:30, should be SLEEP
        ctx = ModeDeterminationContext(
            current_time=dt_time(21, 30),
            sun_above_horizon=False,
            sleep_enabled=True,
            sleep_start_time=dt_time(21, 0),
            sleep_duration_min=60,
            wakeup_enabled=True,
            wakeup_time=dt_time(7, 0),
            wakeup_duration_min=30,
        )
        assert determine_mode(ctx) == Mode.SLEEP

    # --- at_time trigger ---

    def test_at_time_trigger_before_night_start(self):
        """Before night_start_time with at_time trigger is day mode."""
        ctx = ModeDeterminationContext(
            current_time=dt_time(20, 0),
            sun_above_horizon=True,
            night_start_time=dt_time(22, 0),
            night_start_trigger="at_time",
        )
        assert determine_mode(ctx) == Mode.DAY

    def test_at_time_trigger_after_night_start(self):
        """After night_start_time with at_time trigger is night mode."""
        ctx = ModeDeterminationContext(
            current_time=dt_time(23, 0),
            sun_above_horizon=False,
            night_start_time=dt_time(22, 0),
            night_start_trigger="at_time",
        )
        assert determine_mode(ctx) == Mode.NIGHT

    def test_at_time_trigger_morning_before_sunrise(self):
        """Morning before sunrise with at_time trigger is night mode."""
        # 05:00, sun down, next sunrise today → morning (still night)
        ctx = ModeDeterminationContext(
            current_time=dt_time(5, 0),
            sun_above_horizon=False,
            next_sunrise_today=True,
            night_start_time=dt_time(22, 0),
            night_start_trigger="at_time",
        )
        assert determine_mode(ctx) == Mode.NIGHT

    def test_at_time_trigger_evening_after_sunset(self):
        """Evening after sunset with at_time trigger is still day mode."""
        # 20:00, sun down, next sunrise tomorrow → evening (day until night_start)
        ctx = ModeDeterminationContext(
            current_time=dt_time(20, 0),
            sun_above_horizon=False,
            next_sunrise_today=False,
            night_start_time=dt_time(22, 0),
            night_start_trigger="at_time",
        )
        assert determine_mode(ctx) == Mode.DAY
