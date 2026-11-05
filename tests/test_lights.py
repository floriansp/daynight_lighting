"""Tests for lights.py — get_lights_list."""

from __future__ import annotations


from custom_components.daynight_lighting.lights import LightsController


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
