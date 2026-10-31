"""Functional tests for _handle_motion_off (Night mode: motion cleared)."""

from __future__ import annotations


class TestHandleMotionOff:
    """Tests for _handle_motion_off (Night mode motion OFF handler)."""

    def test_schedules_off_timer(self, make_switch, fake_hass):
        """Motion OFF in night mode → schedules off timer via action scheduler."""
        switch, *_ = make_switch(day_mode=False)

        # Mark some lights as controlled (simulating motion ON happened before)
        switch._state_ctrl.mark_controlled(["light.a", "light.b"])

        # Before: no entries in scheduler
        assert len(switch._action_scheduler._entries) == 0

        switch._handle_motion_off()

        # After: one entry scheduled
        assert len(switch._action_scheduler._entries) == 1

    def test_repeated_motion_off_replaces_timer(self, make_switch, fake_hass):
        """Calling _handle_motion_off twice → old timer replaced by new one."""
        switch, *_ = make_switch(day_mode=False)
        switch._state_ctrl.mark_controlled(["light.a"])

        switch._handle_motion_off()
        assert len(switch._action_scheduler._entries) == 1

        switch._handle_motion_off()
        # Old entry removed, new entry added (cancel + schedule)
        assert len(switch._action_scheduler._entries) == 1
