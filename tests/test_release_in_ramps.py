"""Functional tests: resuming control inside sleep and wake-up.

Ending a manual episode, or any other re-apply, must put on the lights what
the next tick would put on them. Inside a ramp that is the ramp, not the day
or night values the schedule would give without it.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from custom_components.daynight_lighting.const import (
    MODE_DAY,
    MODE_NIGHT,
    MODE_SLEEP,
    MODE_WAKEUP,
)


@pytest.fixture
def spied(make_switch, monkeypatch):
    """A switch whose four mode handlers record being driven."""

    def _make(*, day_mode: bool = False, schedule_mode: str = MODE_NIGHT):
        switch, *_ = make_switch(day_mode=day_mode)
        switch._schedule_override = SimpleNamespace(
            get_current_mode=lambda: schedule_mode,
            is_day_mode=lambda: schedule_mode == MODE_DAY,
            get_mode_and_time_for_log=lambda: ("at_time", "22:00"),
        )
        handlers = {mode: switch._get_mode_handler(mode) for mode in
                    (MODE_DAY, MODE_NIGHT, MODE_SLEEP, MODE_WAKEUP)}
        for handler in handlers.values():
            monkeypatch.setattr(handler, "tick", MagicMock())
            monkeypatch.setattr(handler, "handle_motion_on", MagicMock(), raising=False)
        monkeypatch.setattr(handlers[MODE_NIGHT], "enter", MagicMock())
        return switch, handlers

    return _make


def _driven(handlers) -> set[str]:
    driven = {mode for mode, h in handlers.items() if h.tick.called}
    if handlers[MODE_NIGHT].enter.called or handlers[MODE_NIGHT].handle_motion_on.called:
        driven.add(MODE_NIGHT)
    return driven


class TestReleaseDuringServiceModes:
    """Service-started sleep and wake-up outrank the schedule on release."""

    def test_sleep_dimming_continues(self, spied, monkeypatch):
        switch, handlers = spied(schedule_mode=MODE_NIGHT)
        switch._last_mode = MODE_NIGHT
        monkeypatch.setattr(handlers[MODE_SLEEP], "is_sleep_active", lambda: True)

        switch.release_hold()

        assert _driven(handlers) == {MODE_SLEEP}

    def test_sleep_block_keeps_lights_alone(self, spied, monkeypatch):
        switch, handlers = spied(schedule_mode=MODE_NIGHT)
        switch._last_mode = MODE_NIGHT
        sleep = handlers[MODE_SLEEP]
        monkeypatch.setattr(sleep, "is_sleep_active", lambda: False)
        monkeypatch.setattr(sleep, "is_block_active", lambda: True)

        switch.release_hold()

        assert _driven(handlers) == set()

    def test_sleep_block_cleared_in_day_applies_day(self, spied, monkeypatch):
        switch, handlers = spied(day_mode=True, schedule_mode=MODE_DAY)
        switch._last_mode = MODE_DAY
        sleep = handlers[MODE_SLEEP]
        monkeypatch.setattr(sleep, "is_sleep_active", lambda: False)
        monkeypatch.setattr(sleep, "is_block_active", lambda: True)
        sleep.clear_block = MagicMock()

        switch.release_hold()

        sleep.clear_block.assert_called_once()
        assert _driven(handlers) == {MODE_DAY}

    def test_service_wakeup_continues(self, spied, monkeypatch):
        switch, handlers = spied(schedule_mode=MODE_NIGHT)
        switch._last_mode = MODE_NIGHT
        monkeypatch.setattr(
            handlers[MODE_WAKEUP], "is_service_triggered_active", lambda: True
        )

        switch.release_hold()

        assert _driven(handlers) == {MODE_WAKEUP}


class TestReleaseDuringScheduledRamps:
    """A scheduled sleep or wake-up window applies its ramp on release."""

    @pytest.mark.parametrize("mode", [MODE_SLEEP, MODE_WAKEUP])
    def test_ramp_applied(self, spied, mode):
        switch, handlers = spied(schedule_mode=mode)
        switch._last_mode = mode

        switch.release_hold()

        assert _driven(handlers) == {mode}

    def test_day_still_applies_day(self, spied):
        switch, handlers = spied(day_mode=True, schedule_mode=MODE_DAY)
        switch._last_mode = MODE_DAY

        switch.release_hold()

        assert _driven(handlers) == {MODE_DAY}

    def test_night_release_turns_off_when_motion_is_gone(self, spied, monkeypatch):
        switch, handlers = spied(schedule_mode=MODE_NIGHT)
        switch._last_mode = MODE_NIGHT
        night = handlers[MODE_NIGHT]
        monkeypatch.setattr(night, "_turn_off_lights", MagicMock())

        switch.release_hold()

        # With motion gone, a motion-lit night is "off": releasing the hold
        # turns the room back off through the off timer's own selection.
        night._turn_off_lights.assert_called_once()
        assert _driven(handlers) == set()


class TestReapplyCurrentMode:
    """Dials and the scene blocker re-apply through the same priority."""

    def test_service_sleep_outranks_night(self, spied, monkeypatch):
        switch, handlers = spied(schedule_mode=MODE_NIGHT)
        monkeypatch.setattr(handlers[MODE_SLEEP], "is_sleep_active", lambda: True)

        switch.reapply_current_mode()

        assert _driven(handlers) == {MODE_SLEEP}

    def test_hold_release_in_service_wakeup(self, spied, monkeypatch):
        switch, handlers = spied(day_mode=True, schedule_mode=MODE_DAY)
        monkeypatch.setattr(
            handlers[MODE_WAKEUP], "is_service_triggered_active", lambda: True
        )

        switch.release_hold()

        assert _driven(handlers) == {MODE_WAKEUP}

    def test_without_service_mode_applies_schedule(self, spied):
        switch, handlers = spied(day_mode=True, schedule_mode=MODE_DAY)

        switch.reapply_current_mode()

        assert _driven(handlers) == {MODE_DAY}


class TestTickPriorityUnchanged:
    """The tick keeps its order: sleep, block, service wake-up, schedule."""

    def test_service_sleep_skips_schedule(self, spied, monkeypatch):
        switch, handlers = spied(day_mode=True, schedule_mode=MODE_DAY)
        switch._last_mode = MODE_DAY
        monkeypatch.setattr(handlers[MODE_SLEEP], "is_sleep_active", lambda: True)

        switch._handle_tick()

        assert _driven(handlers) == {MODE_SLEEP}
        assert switch._last_mode == MODE_DAY

    def test_schedule_mode_when_no_service_mode(self, spied):
        switch, handlers = spied(day_mode=True, schedule_mode=MODE_DAY)
        switch._last_mode = MODE_DAY

        switch._handle_tick()

        assert _driven(handlers) == {MODE_DAY}
