"""Pure schedule and mode determination functions.

All functions in this module are pure - they have no side effects,
no I/O, and depend only on their inputs. They can be unit tested
without any Home Assistant dependencies.

These functions handle:
- Time window calculations
- Mode determination (day/night/sleep/wakeup)
- Progress tracking for gradual transitions
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import time as dt_time

from .models import Mode


def time_to_minutes(time: dt_time) -> int:
    """Convert time to minutes since midnight.

    Pure function for time calculations.

    Args:
        time: Time object to convert

    Returns:
        Minutes since midnight (0-1439)

    Examples:
        >>> time_to_minutes(dt_time(0, 0))
        0
        >>> time_to_minutes(dt_time(12, 30))
        750
        >>> time_to_minutes(dt_time(23, 59))
        1439
    """
    return time.hour * 60 + time.minute


def is_in_time_window(
    current_time: dt_time,
    window_start: dt_time,
    window_end: dt_time,
) -> bool:
    """Check if current time falls within a time window.

    Handles windows that cross midnight (e.g., 23:00-01:00).

    This is a pure function with no dependency on the current system time.

    Args:
        current_time: The time to check
        window_start: Start of the time window
        window_end: End of the time window

    Returns:
        True if current_time is within [window_start, window_end)

    Examples:
        >>> # Normal window (same day)
        >>> is_in_time_window(dt_time(14, 0), dt_time(12, 0), dt_time(16, 0))
        True

        >>> # Before window
        >>> is_in_time_window(dt_time(10, 0), dt_time(12, 0), dt_time(16, 0))
        False

        >>> # Window crossing midnight
        >>> is_in_time_window(dt_time(0, 30), dt_time(23, 0), dt_time(1, 0))
        True

        >>> # Before midnight crossing window
        >>> is_in_time_window(dt_time(22, 0), dt_time(23, 0), dt_time(1, 0))
        False
    """
    current = time_to_minutes(current_time)
    start = time_to_minutes(window_start)
    end = time_to_minutes(window_end)

    if start <= end:
        # Normal case: window within same day (e.g., 12:00-16:00)
        return start <= current < end
    else:
        # Wrap case: window crosses midnight (e.g., 23:00-01:00)
        # Active from start to midnight, or midnight to end
        return current >= start or current < end


def calculate_progress_ratio(
    current_time: dt_time,
    window_start: dt_time,
    window_end: dt_time,
) -> float:
    """Calculate progress (0.0-1.0) through a time window.

    Used for gradual transitions like sleep mode dimming or
    wake-up mode brightening.

    This is a pure function with no side effects.

    Args:
        current_time: Current time within the window
        window_start: Start of the transition window
        window_end: End of the transition window

    Returns:
        Progress ratio (0.0 at start, 1.0 at end, clamped to [0, 1])

    Examples:
        >>> # Halfway through
        >>> calculate_progress_ratio(dt_time(14, 0), dt_time(12, 0), dt_time(16, 0))
        0.5

        >>> # At start
        >>> calculate_progress_ratio(dt_time(12, 0), dt_time(12, 0), dt_time(16, 0))
        0.0

        >>> # Window crossing midnight (at 00:30 of 23:00-01:00 window)
        >>> calculate_progress_ratio(dt_time(0, 30), dt_time(23, 0), dt_time(1, 0))
        0.25

        >>> # Clamped to 1.0 if past end
        >>> calculate_progress_ratio(dt_time(17, 0), dt_time(12, 0), dt_time(16, 0))
        1.0
    """
    current = time_to_minutes(current_time)
    start = time_to_minutes(window_start)
    end = time_to_minutes(window_end)

    # Handle wrap case (window crosses midnight)
    if start > end:
        # Add 24 hours to times after midnight for calculation
        if current < end:
            current += 1440  # Add 24 hours in minutes
        end += 1440

    # Calculate duration and progress
    duration = end - start
    elapsed = current - start

    if duration <= 0:
        return 1.0  # Avoid division by zero

    progress = elapsed / duration
    return max(0.0, min(1.0, progress))


def calculate_time_after(
    start_time: dt_time,
    duration_minutes: int,
) -> dt_time:
    """Calculate the time after adding duration to a start time.

    Handles wrapping past midnight.

    Args:
        start_time: Starting time
        duration_minutes: Duration to add in minutes

    Returns:
        Resulting time after adding duration

    Examples:
        >>> calculate_time_after(dt_time(22, 0), 60)
        datetime.time(23, 0)

        >>> calculate_time_after(dt_time(23, 30), 120)
        datetime.time(1, 30)

        >>> calculate_time_after(dt_time(12, 0), 0)
        datetime.time(12, 0)
    """
    start_minutes = time_to_minutes(start_time)
    end_minutes = (start_minutes + duration_minutes) % 1440

    hours = end_minutes // 60
    minutes = end_minutes % 60

    return dt_time(hours, minutes)


def calculate_time_before(
    end_time: dt_time,
    duration_minutes: int,
) -> dt_time:
    """Calculate the time before a given time by subtracting duration.

    Handles wrapping before midnight.

    Args:
        end_time: End time
        duration_minutes: Duration to subtract in minutes

    Returns:
        Starting time before the end time

    Examples:
        >>> calculate_time_before(dt_time(7, 0), 30)
        datetime.time(6, 30)

        >>> calculate_time_before(dt_time(1, 0), 120)
        datetime.time(23, 0)
    """
    end_minutes = time_to_minutes(end_time)
    start_minutes = (end_minutes - duration_minutes) % 1440

    hours = start_minutes // 60
    minutes = start_minutes % 60

    return dt_time(hours, minutes)


@dataclass(frozen=True)
class ModeDeterminationContext:
    """Input context for mode determination.

    This is a pure data class that contains all inputs needed to
determine the current operating mode without any Home Assistant
    dependencies.
    """

    # Current time
    current_time: dt_time

    # Sun state (optional, can be None if sun unavailable)
    sun_above_horizon: bool | None = None
    next_sunrise_today: bool | None = None  # True if next sunrise is today

    # Sleep mode configuration
    sleep_enabled: bool = False
    sleep_start_time: dt_time | None = None
    sleep_duration_min: int = 0

    # Wake-up mode configuration
    wakeup_enabled: bool = False
    wakeup_time: dt_time | None = None
    wakeup_duration_min: int = 0

    # Night mode configuration
    night_start_time: dt_time | None = None
    night_start_trigger: str = "sun_below_horizon"


def determine_mode(context: ModeDeterminationContext) -> Mode:
    """Determine the current operating mode from context.

    This is a pure function that takes all necessary inputs and returns
the appropriate mode. It has no side effects and no I/O.

    Mode priority (highest to lowest):
    1. Sleep mode (if enabled and in sleep window)
    2. Wake-up mode (if enabled and in wake-up window)
    3. Day/Night mode (based on sun position or configured times)

    Args:
        context: Mode determination context with all necessary inputs

    Returns:
        The current operating mode

    Examples:
        >>> # Sleep mode takes priority
        >>> ctx = ModeDeterminationContext(
        ...     current_time=dt_time(22, 0),
        ...     sleep_enabled=True,
        ...     sleep_start_time=dt_time(21, 0),
        ...     sleep_duration_min=60,
        ...     sun_above_horizon=False,
        ... )
        >>> determine_mode(ctx)
        <Mode.SLEEP: 'sleep'>

        >>> # Day mode when sun is up
        >>> ctx = ModeDeterminationContext(
        ...     current_time=dt_time(14, 0),
        ...     sun_above_horizon=True,
        ... )
        >>> determine_mode(ctx)
        <Mode.DAY: 'day'>

        >>> # Night mode when sun is down
        >>> ctx = ModeDeterminationContext(
        ...     current_time=dt_time(23, 0),
        ...     sun_above_horizon=False,
        ... )
        >>> determine_mode(ctx)
        <Mode.NIGHT: 'night'>
    """
    # Priority 1: Check for sleep mode
    if context.sleep_enabled and context.sleep_start_time is not None:
        sleep_start = context.sleep_start_time
        sleep_end = calculate_time_after(
            sleep_start,
            context.sleep_duration_min,
        )

        if is_in_time_window(context.current_time, sleep_start, sleep_end):
            return Mode.SLEEP

    # Priority 2: Check for wake-up mode
    if context.wakeup_enabled and context.wakeup_time is not None:
        wakeup_end = context.wakeup_time
        wakeup_start = calculate_time_before(
            wakeup_end,
            context.wakeup_duration_min,
        )

        if is_in_time_window(context.current_time, wakeup_start, wakeup_end):
            return Mode.WAKEUP

    # Priority 3: Determine day/night from base logic
    if _is_day_mode(context):
        return Mode.DAY
    else:
        return Mode.NIGHT


def _is_day_mode(context: ModeDeterminationContext) -> bool:
    """Determine if currently in day mode (not night mode).

    This is the base day/night determination excluding sleep/wake modes.

    Args:
        context: Mode determination context

    Returns:
        True for day mode, False for night mode
    """
    trigger = context.night_start_trigger

    if trigger == "at_time":
        return _is_day_mode_at_time(context)
    else:
        # Default: sun_below_horizon
        return _is_day_mode_sun_based(context)


def _is_day_mode_at_time(context: ModeDeterminationContext) -> bool:
    """Day mode determination when using configured time.

    Uses the configured night_start_time to determine day vs night.

    Args:
        context: Mode determination context

    Returns:
        True for day mode, False for night mode
    """
    if context.night_start_time is None:
        # Fallback to sun-based if no time configured
        return _is_day_mode_sun_based(context)

    current = context.current_time
    night_start = context.night_start_time

    # Create day window: from night_start (previous day) to night_start (today)
    # This is a bit tricky - we need to check if we're in the night window
    # Night window: night_start to next day's night_start
    # Day window: after night_start passes, until next night_start

    # If current time >= night_start, we're in night mode
    current_min = time_to_minutes(current)
    night_start_min = time_to_minutes(night_start)

    if current_min >= night_start_min:
        # Past night start time - night mode
        return False

    # Before night start time - could be day or still night from yesterday
    # Check if sun is available for additional context
    if context.sun_above_horizon is True:
        # Sun is up and before night start - day mode
        return True

    if context.sun_above_horizon is False:
        # Sun is down - need to determine if morning or evening
        # If next sunrise is tomorrow, we're in evening (still day until night_start)
        # If next sunrise is today, we're in morning (still night)
        if context.next_sunrise_today is False:
            # Next sunrise is tomorrow - evening, still day
            return True
        else:
            # Next sunrise is today - morning, still night
            return False

    # No sun data available - assume day if before night_start
    return True


def _is_day_mode_sun_based(context: ModeDeterminationContext) -> bool:
    """Day mode determination based on sun position only.

    Simple logic: day when sun is above horizon, night when below.

    Args:
        context: Mode determination context

    Returns:
        True for day mode, False for night mode
    """
    if context.sun_above_horizon is not None:
        return context.sun_above_horizon

    # No sun data - default to day mode as safe fallback
    return True
