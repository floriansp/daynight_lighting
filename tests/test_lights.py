"""Tests for lights.py — get_lights_list, get_lights_that_are_off, snapshot_lights."""

from __future__ import annotations


from custom_components.daynight_lighting.lights import LightsController

from tests.conftest import FakeState


class TestGetLightsList:
    """Tests for LightsController.get_lights_list."""

    def test_normal_list(self, fake_hass):
        ctrl = LightsController(fake_hass, ["light.a", "light.b"], "Test")
        assert ctrl.get_lights_list() == ["light.a", "light.b"]

    def test_empty_list(self, fake_hass):
        ctrl = LightsController(fake_hass, [], "Test")
        assert ctrl.get_lights_list() == []

    def test_returns_copy(self, fake_hass):
        """Returned list should be a new list (not the same reference)."""
        original = ["light.a"]
        ctrl = LightsController(fake_hass, original, "Test")
        result = ctrl.get_lights_list()
        assert result == original
        assert result is not original


# ===================================================================
#  LightsController.get_lights_that_are_off
# ===================================================================


class TestGetLightsThatAreOff:
    """Tests for get_lights_that_are_off."""

    def test_all_off(self, fake_hass):
        fake_hass.states.set("light.a", FakeState(state="off"))
        fake_hass.states.set("light.b", FakeState(state="off"))
        ctrl = LightsController(fake_hass, {}, "Test")
        result = ctrl.get_lights_that_are_off(["light.a", "light.b"])
        assert result == ["light.a", "light.b"]

    def test_all_on(self, fake_hass):
        fake_hass.states.set("light.a", FakeState(state="on"))
        fake_hass.states.set("light.b", FakeState(state="on"))
        ctrl = LightsController(fake_hass, {}, "Test")
        result = ctrl.get_lights_that_are_off(["light.a", "light.b"])
        assert result == []

    def test_mixed(self, fake_hass):
        fake_hass.states.set("light.a", FakeState(state="on"))
        fake_hass.states.set("light.b", FakeState(state="off"))
        ctrl = LightsController(fake_hass, {}, "Test")
        result = ctrl.get_lights_that_are_off(["light.a", "light.b"])
        assert result == ["light.b"]

    def test_missing_entity_treated_as_off(self, fake_hass):
        """Entity not in hass.states → treated as off (state is None)."""
        ctrl = LightsController(fake_hass, {}, "Test")
        result = ctrl.get_lights_that_are_off(["light.missing"])
        assert result == ["light.missing"]

    def test_unavailable_treated_as_off(self, fake_hass):
        fake_hass.states.set("light.a", FakeState(state="unavailable"))
        ctrl = LightsController(fake_hass, {}, "Test")
        result = ctrl.get_lights_that_are_off(["light.a"])
        assert result == ["light.a"]

    def test_empty_list(self, fake_hass):
        ctrl = LightsController(fake_hass, {}, "Test")
        assert ctrl.get_lights_that_are_off([]) == []


# ===================================================================
#  LightsController.snapshot_lights
# ===================================================================


class TestSnapshotLights:
    """Tests for snapshot_lights."""

    def test_basic_snapshot(self, fake_hass):
        fake_hass.states.set(
            "light.a",
            FakeState(state="on", attributes={"brightness": 200, "color_temp": 350}),
        )
        ctrl = LightsController(fake_hass, {}, "Test")
        snap = ctrl.snapshot_lights(["light.a"])
        assert snap == {"light.a": ("on", 200, 350)}

    def test_missing_entity(self, fake_hass):
        ctrl = LightsController(fake_hass, {}, "Test")
        snap = ctrl.snapshot_lights(["light.missing"])
        assert snap == {"light.missing": ("unknown", None, None)}

    def test_no_brightness_no_color(self, fake_hass):
        fake_hass.states.set("light.a", FakeState(state="on", attributes={}))
        ctrl = LightsController(fake_hass, {}, "Test")
        snap = ctrl.snapshot_lights(["light.a"])
        assert snap == {"light.a": ("on", None, None)}

    def test_invalid_color_temp(self, fake_hass):
        """Non-numeric color_temp → stored as None."""
        fake_hass.states.set(
            "light.a",
            FakeState(state="on", attributes={"brightness": 128, "color_temp": "invalid"}),
        )
        ctrl = LightsController(fake_hass, {}, "Test")
        snap = ctrl.snapshot_lights(["light.a"])
        assert snap == {"light.a": ("on", 128, None)}

    def test_multiple_lights(self, fake_hass):
        fake_hass.states.set(
            "light.a",
            FakeState(state="on", attributes={"brightness": 200, "color_temp": 300}),
        )
        fake_hass.states.set(
            "light.b",
            FakeState(state="off", attributes={}),
        )
        ctrl = LightsController(fake_hass, {}, "Test")
        snap = ctrl.snapshot_lights(["light.a", "light.b"])
        assert snap["light.a"] == ("on", 200, 300)
        assert snap["light.b"] == ("off", None, None)

    def test_color_temp_float_converted_to_int(self, fake_hass):
        """Float color_temp → converted via int()."""
        fake_hass.states.set(
            "light.a",
            FakeState(state="on", attributes={"color_temp": 350.7}),
        )
        ctrl = LightsController(fake_hass, {}, "Test")
        snap = ctrl.snapshot_lights(["light.a"])
        assert snap["light.a"] == ("on", None, 350)

    def test_empty_lights_list(self, fake_hass):
        ctrl = LightsController(fake_hass, {}, "Test")
        assert ctrl.snapshot_lights([]) == {}
