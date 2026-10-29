"""Tests for state_controller.py — all set/query methods."""

from __future__ import annotations

import pytest

from custom_components.daynight_lighting.state_controller import (
    HOLD_REASON_DETECTED,
    HOLD_REASON_SERVICE,
    StateController,
)


def _make_controller(fake_hass, fake_store, instance_name="Test"):
    """Create a StateController with the FakeStore injected."""
    ctrl = StateController(fake_hass, "test_entry", instance_name)
    ctrl._store = fake_store
    return ctrl


# ===================================================================
#  mark / unmark controlled
# ===================================================================


class TestMarkControlled:
    """Tests for mark_controlled and unmark_controlled."""

    def test_mark_controlled(self, fake_hass, fake_store):
        ctrl = _make_controller(fake_hass, fake_store)
        ctrl.mark_controlled(["light.a", "light.b"])
        assert ctrl.is_controlled_by_us("light.a")
        assert ctrl.is_controlled_by_us("light.b")
        assert not ctrl.is_controlled_by_us("light.c")

    def test_mark_controlled_idempotent(self, fake_hass, fake_store):
        ctrl = _make_controller(fake_hass, fake_store)
        ctrl.mark_controlled(["light.a"])
        ctrl.mark_controlled(["light.a"])
        assert ctrl.get_lights_we_control() == {"light.a"}

    def test_unmark_controlled(self, fake_hass, fake_store):
        ctrl = _make_controller(fake_hass, fake_store)
        ctrl.mark_controlled(["light.a", "light.b"])
        ctrl.unmark_controlled(["light.a"])
        assert not ctrl.is_controlled_by_us("light.a")
        assert ctrl.is_controlled_by_us("light.b")

    def test_unmark_controlled_leaves_holds_alone(self, fake_hass, fake_store):
        """Unmarking control must not release a hold: the two are independent."""
        ctrl = _make_controller(fake_hass, fake_store)
        ctrl.mark_controlled(["light.a"])
        ctrl.set_hold(["light.a"], reason=HOLD_REASON_SERVICE)
        ctrl.unmark_controlled(["light.a"])
        assert not ctrl.is_controlled_by_us("light.a")
        assert ctrl.is_held("light.a")

    def test_unmark_nonexistent_no_error(self, fake_hass, fake_store):
        ctrl = _make_controller(fake_hass, fake_store)
        ctrl.unmark_controlled(["light.nonexistent"])  # should not raise


# ===================================================================
#  holds (set / release / clear)
# ===================================================================


class TestHold:
    """Tests for set_hold, release_hold, clear_holds and reason tracking."""

    def test_set_hold_records_the_reason(self, fake_hass, fake_store):
        ctrl = _make_controller(fake_hass, fake_store)
        ctrl.set_hold(["light.a"], reason=HOLD_REASON_DETECTED)
        assert ctrl.is_held("light.a")
        assert ctrl.get_hold_reason("light.a") == HOLD_REASON_DETECTED

    def test_set_hold_defaults_to_service(self, fake_hass, fake_store):
        ctrl = _make_controller(fake_hass, fake_store)
        ctrl.set_hold(["light.a"])
        assert ctrl.get_hold_reason("light.a") == HOLD_REASON_SERVICE

    def test_set_hold_is_per_light(self, fake_hass, fake_store):
        ctrl = _make_controller(fake_hass, fake_store)
        ctrl.set_hold(["light.a"], reason=HOLD_REASON_DETECTED)
        ctrl.set_hold(["light.b"], reason=HOLD_REASON_SERVICE)
        assert ctrl.get_held_lights_with_reasons() == {
            "light.a": HOLD_REASON_DETECTED,
            "light.b": HOLD_REASON_SERVICE,
        }

    def test_release_hold_specific_light(self, fake_hass, fake_store):
        ctrl = _make_controller(fake_hass, fake_store)
        ctrl.set_hold(["light.a", "light.b"])
        ctrl.release_hold(["light.a"])
        assert not ctrl.is_held("light.a")
        assert ctrl.is_held("light.b")

    def test_release_hold_all(self, fake_hass, fake_store):
        ctrl = _make_controller(fake_hass, fake_store)
        ctrl.set_hold(["light.a", "light.b"])
        ctrl.release_hold()
        assert ctrl.get_held_lights() == set()
        assert ctrl.get_hold_count() == 0

    def test_clear_holds(self, fake_hass, fake_store):
        ctrl = _make_controller(fake_hass, fake_store)
        ctrl.set_hold(["light.a", "light.b"])
        ctrl.clear_holds()
        assert ctrl.get_held_lights() == set()
        assert ctrl.get_hold_count() == 0

    def test_clear_holds_keep_detected(self, fake_hass, fake_store):
        ctrl = _make_controller(fake_hass, fake_store)
        ctrl.set_hold(["light.a"], reason=HOLD_REASON_DETECTED)
        ctrl.set_hold(["light.b"], reason=HOLD_REASON_SERVICE)

        ctrl.clear_holds(keep_detected=True)

        assert ctrl.get_held_lights() == {"light.a"}
        assert ctrl.get_hold_reason("light.a") == HOLD_REASON_DETECTED
        assert ctrl.get_hold_reason("light.b") is None

    def test_get_hold_count(self, fake_hass, fake_store):
        ctrl = _make_controller(fake_hass, fake_store)
        assert ctrl.get_hold_count() == 0
        ctrl.set_hold(["light.a", "light.b"])
        assert ctrl.get_hold_count() == 2

    def test_get_hold_reason_missing(self, fake_hass, fake_store):
        ctrl = _make_controller(fake_hass, fake_store)
        assert ctrl.get_hold_reason("light.a") is None


# ===================================================================
#  prune
# ===================================================================


class TestPrune:
    """Tests for prune (remove stale entity_ids)."""

    def test_prune_removes_stale(self, fake_hass, fake_store):
        ctrl = _make_controller(fake_hass, fake_store)
        ctrl.mark_controlled(["light.a", "light.stale"])
        ctrl.set_hold(["light.stale"])
        ctrl.prune(["light.a"])
        assert ctrl.is_controlled_by_us("light.a")
        assert not ctrl.is_controlled_by_us("light.stale")
        assert not ctrl.is_held("light.stale")

    def test_prune_no_change(self, fake_hass, fake_store):
        ctrl = _make_controller(fake_hass, fake_store)
        ctrl.mark_controlled(["light.a"])
        ctrl.prune(["light.a", "light.b"])
        assert ctrl.is_controlled_by_us("light.a")


# ===================================================================
#  clear
# ===================================================================


class TestClear:
    """Tests for clear."""

    def test_clear_all(self, fake_hass, fake_store):
        ctrl = _make_controller(fake_hass, fake_store)
        ctrl.mark_controlled(["light.a", "light.b"])
        ctrl.set_hold(["light.a"])
        ctrl.clear()
        assert ctrl.get_lights_we_control() == set()
        assert ctrl.get_held_lights() == set()

    def test_clear_holds_keeps_controlled(self, fake_hass, fake_store):
        """Clearing holds does not stop managing the light."""
        ctrl = _make_controller(fake_hass, fake_store)
        ctrl.mark_controlled(["light.a", "light.b"])
        ctrl.set_hold(["light.a"])

        ctrl.clear_holds()

        assert ctrl.get_held_lights() == set()
        assert ctrl.is_controlled_by_us("light.a")


# ===================================================================
#  _data_to_save
# ===================================================================


class TestDataToSave:
    """Tests for _data_to_save (serialisation format)."""

    def test_sorted_lists(self, fake_hass, fake_store):
        ctrl = _make_controller(fake_hass, fake_store)
        ctrl.mark_controlled(["light.c", "light.a", "light.b"])
        ctrl.set_hold(["light.c", "light.a"])
        data = ctrl._data_to_save()
        assert data["lights_we_control"] == ["light.a", "light.b", "light.c"]
        assert data["held_lights"] == {"light.a": HOLD_REASON_SERVICE, "light.c": HOLD_REASON_SERVICE}

    def test_empty(self, fake_hass, fake_store):
        ctrl = _make_controller(fake_hass, fake_store)
        data = ctrl._data_to_save()
        assert data == {
            "lights_we_control": [],
            "held_lights": {},
            "lux_calibration": None,
            "expected_states": {},
        }


# ===================================================================
#  async_load
# ===================================================================


class TestAsyncLoad:
    """Tests for async_load (loading persisted state)."""

    @pytest.mark.asyncio
    async def test_load_existing_data(self, fake_hass, fake_store):
        fake_store._data = {
            "lights_we_control": ["light.a", "light.b"],
            "held_lights": {"light.a": HOLD_REASON_DETECTED},
        }
        ctrl = _make_controller(fake_hass, fake_store)
        await ctrl.async_load()
        assert ctrl.is_controlled_by_us("light.a")
        assert ctrl.is_controlled_by_us("light.b")
        assert ctrl.get_hold_reason("light.a") == HOLD_REASON_DETECTED

    @pytest.mark.asyncio
    async def test_load_no_data(self, fake_hass, fake_store):
        """First start, no persisted data."""
        ctrl = _make_controller(fake_hass, fake_store)
        await ctrl.async_load()
        assert ctrl.get_lights_we_control() == set()

    @pytest.mark.asyncio
    async def test_round_trip(self, fake_hass, fake_store):
        """Save and reload preserves state."""
        ctrl = _make_controller(fake_hass, fake_store)
        ctrl.mark_controlled(["light.a", "light.b"])
        ctrl.set_hold(["light.a"], reason=HOLD_REASON_DETECTED)
        ctrl2 = _make_controller(fake_hass, fake_store, "Test2")
        await ctrl2.async_load()
        assert ctrl2.is_controlled_by_us("light.a")
        assert ctrl2.is_controlled_by_us("light.b")
        assert ctrl2.get_hold_reason("light.a") == HOLD_REASON_DETECTED

    @pytest.mark.asyncio
    async def test_load_migrates_legacy_held_list(self, fake_hass, fake_store):
        """Older versions stored held_lights as a list; those were service holds."""
        fake_store._data = {
            "lights_we_control": [],
            "held_lights": ["light.a", "light.b"],
        }
        ctrl = _make_controller(fake_hass, fake_store)
        await ctrl.async_load()
        assert ctrl.get_held_lights_with_reasons() == {
            "light.a": HOLD_REASON_SERVICE,
            "light.b": HOLD_REASON_SERVICE,
        }


# ===================================================================
#  LUX Calibration
# ===================================================================


class TestLuxCalibration:
    """Tests for LUX calibration storage."""

    def test_default_no_calibration(self, fake_hass, fake_store):
        """No calibration by default."""
        ctrl = _make_controller(fake_hass, fake_store)
        assert ctrl.get_lux_calibration() is None

    def test_set_and_get_calibration(self, fake_hass, fake_store):
        """Set and retrieve calibration."""
        ctrl = _make_controller(fake_hass, fake_store)
        ctrl.set_lux_calibration(123.45)
        assert ctrl.get_lux_calibration() == 123.45

    def test_calibration_saved(self, fake_hass, fake_store):
        """Calibration is persisted."""
        ctrl = _make_controller(fake_hass, fake_store)
        ctrl.set_lux_calibration(100.0)
        data = ctrl._data_to_save()
        assert data["lux_calibration"] == 100.0

    @pytest.mark.asyncio
    async def test_calibration_loaded(self, fake_hass, fake_store):
        """Calibration is loaded from storage."""
        fake_store._data = {
            "lights_we_control": [],
            "held_lights": {},
            "lux_calibration": 200.5,
        }
        ctrl = _make_controller(fake_hass, fake_store)
        await ctrl.async_load()
        assert ctrl.get_lux_calibration() == 200.5

    @pytest.mark.asyncio
    async def test_calibration_round_trip(self, fake_hass, fake_store):
        """Calibration survives save-reload cycle."""
        ctrl = _make_controller(fake_hass, fake_store)
        ctrl.set_lux_calibration(150.75)
        ctrl2 = _make_controller(fake_hass, fake_store, "Test2")
        await ctrl2.async_load()
        assert ctrl2.get_lux_calibration() == 150.75
