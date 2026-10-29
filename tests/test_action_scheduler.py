"""Tests for action_scheduler.py — _source_label + add/remove/run_due."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone


from custom_components.daynight_lighting.action_scheduler import (
    ActionScheduler,
    _source_label,
)


# ===================================================================
#  _source_label — pure function
# ===================================================================


class TestSourceLabel:
    """Tests for the _source_label helper."""

    def test_with_reason(self):
        assert _source_label("MotionController", "motion_off") == "MotionController (motion_off)"

    def test_without_reason(self):
        assert _source_label("MotionController", None) == "MotionController"

    def test_empty_reason(self):
        """Empty string is falsy → treated as no reason."""
        assert _source_label("Ctrl", "") == "Ctrl"


# ===================================================================
#  ActionScheduler — add / remove
# ===================================================================


class TestAddRemove:
    """Tests for add and remove entry management."""

    def _make_scheduler(self, fake_hass):
        return ActionScheduler(fake_hass, "Test")

    def test_add_creates_entry(self, fake_hass):
        sched = self._make_scheduler(fake_hass)
        run_at = datetime.now(timezone.utc) + timedelta(minutes=5)
        sched.add(
            run_at=run_at,
            cancel_key="key1",
            source="Motion",
            lights_for_log=["light.a"],
            callback_fn=lambda: (["light.a"], None),
        )
        assert len(sched._entries) == 1
        assert sched._entries[0]["cancel_key"] == "key1"

    def test_add_schedules_timer(self, fake_hass):
        sched = self._make_scheduler(fake_hass)
        run_at = datetime.now(timezone.utc) + timedelta(minutes=5)
        sched.add(
            run_at=run_at,
            cancel_key="key1",
            source="Motion",
            lights_for_log=["light.a"],
            callback_fn=lambda: (["light.a"], None),
        )
        # Should have called loop.call_later
        fake_hass.loop.call_later.assert_called()

    def test_remove_by_key(self, fake_hass):
        sched = self._make_scheduler(fake_hass)
        run_at = datetime.now(timezone.utc) + timedelta(minutes=5)
        sched.add(
            run_at=run_at,
            cancel_key="key1",
            source="Motion",
            lights_for_log=["light.a"],
            callback_fn=lambda: (["light.a"], None),
        )
        sched.add(
            run_at=run_at,
            cancel_key="key2",
            source="Motion",
            lights_for_log=["light.b"],
            callback_fn=lambda: (["light.b"], None),
        )
        assert len(sched._entries) == 2
        sched.remove("key1")
        assert len(sched._entries) == 1
        assert sched._entries[0]["cancel_key"] == "key2"

    def test_remove_nonexistent_key(self, fake_hass):
        sched = self._make_scheduler(fake_hass)
        sched.remove("nonexistent")  # should not raise

    def test_remove_all_same_key(self, fake_hass):
        sched = self._make_scheduler(fake_hass)
        run_at = datetime.now(timezone.utc) + timedelta(minutes=5)
        for _ in range(3):
            sched.add(
                run_at=run_at,
                cancel_key="same_key",
                source="Motion",
                lights_for_log=["light.a"],
                callback_fn=lambda: (["light.a"], None),
            )
        assert len(sched._entries) == 3
        sched.remove("same_key")
        assert len(sched._entries) == 0


# ===================================================================
#  ActionScheduler — _run_due
# ===================================================================


class TestRunDue:
    """Tests for _run_due (callback execution)."""

    def test_run_due_calls_turn_off(self, fake_hass):
        """Due entry with entity_ids → calls light.turn_off."""
        sched = ActionScheduler(fake_hass, "Test")
        # Add an entry that is already past due
        run_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        sched._entries.append({
            "run_at": run_at,
            "cancel_key": "key1",
            "source": "Motion",
            "reason": "motion_off",
            "callback": lambda: (["light.a", "light.b"], None),
        })
        sched._run_due()
        # Should have called async_create_task → services.async_call
        fake_hass.services.async_call.assert_called_once_with(
            "light", "turn_off", {"entity_id": ["light.a", "light.b"]}
        )

    def test_run_due_skip_reason(self, fake_hass):
        """Callback returns skip_reason → no turn_off call."""
        sched = ActionScheduler(fake_hass, "Test")
        run_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        sched._entries.append({
            "run_at": run_at,
            "cancel_key": "key1",
            "source": "Motion",
            "reason": "motion_off",
            "callback": lambda: ([], "manual control active"),
        })
        sched._run_due()
        fake_hass.services.async_call.assert_not_called()

    def test_run_due_empty_entity_ids(self, fake_hass):
        """Callback returns empty list and no skip_reason → no turn_off call."""
        sched = ActionScheduler(fake_hass, "Test")
        run_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        sched._entries.append({
            "run_at": run_at,
            "cancel_key": "key1",
            "source": "Motion",
            "reason": None,
            "callback": lambda: ([], None),
        })
        sched._run_due()
        fake_hass.services.async_call.assert_not_called()

    def test_run_due_removes_entry(self, fake_hass):
        """After running, due entry is removed."""
        sched = ActionScheduler(fake_hass, "Test")
        run_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        sched._entries.append({
            "run_at": run_at,
            "cancel_key": "key1",
            "source": "Motion",
            "reason": None,
            "callback": lambda: (["light.a"], None),
        })
        sched._run_due()
        assert len(sched._entries) == 0

    def test_run_due_keeps_future_entries(self, fake_hass):
        """Entries in the future are not run."""
        sched = ActionScheduler(fake_hass, "Test")
        past = datetime.now(timezone.utc) - timedelta(seconds=1)
        future = datetime.now(timezone.utc) + timedelta(minutes=5)
        sched._entries = [
            {
                "run_at": past,
                "cancel_key": "past",
                "source": "Motion",
                "reason": None,
                "callback": lambda: (["light.a"], None),
            },
            {
                "run_at": future,
                "cancel_key": "future",
                "source": "Motion",
                "reason": None,
                "callback": lambda: (["light.b"], None),
            },
        ]
        sched._run_due()
        assert len(sched._entries) == 1
        assert sched._entries[0]["cancel_key"] == "future"

    def test_callback_exception_handled(self, fake_hass):
        """Exception in callback is caught, doesn't crash scheduler."""
        sched = ActionScheduler(fake_hass, "Test")
        run_at = datetime.now(timezone.utc) - timedelta(seconds=1)

        def bad_callback():
            raise RuntimeError("boom")

        sched._entries.append({
            "run_at": run_at,
            "cancel_key": "key1",
            "source": "Motion",
            "reason": None,
            "callback": bad_callback,
        })
        sched._run_due()  # should not raise
        assert len(sched._entries) == 0
