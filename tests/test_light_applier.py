"""Tests for LightApplier — the single entry point for switching lights."""

from __future__ import annotations

import pytest

from custom_components.daynight_lighting.light_applier import LightApplier
from custom_components.daynight_lighting.state_controller import StateController


def _make_applier(
    fake_hass, fake_store, transition_sec: int = 2, mark_applied=None
):
    """Create an applier with a real state controller and a fake store."""
    state_ctrl = StateController(fake_hass, "test_entry", "Test")
    state_ctrl._store = fake_store
    applier = LightApplier(
        fake_hass,
        state_ctrl,
        lambda _context: transition_sec,
        "Test",
        mark_applied=mark_applied,
    )
    return applier, state_ctrl


def _light_call(fake_hass):
    """Return (service, payload) of the last light service call."""
    domain, service, payload = fake_hass.services.async_call.call_args[0]
    assert domain == "light"
    return service, payload


class TestTurnOn:
    """Turning on must call the service and record the expected values."""

    def test_calls_service_with_transition(self, fake_hass, fake_store):
        applier, _ = _make_applier(fake_hass, fake_store)

        applier.turn_on(
            ["light.a"],
            {"entity_id": ["light.a"], "brightness_pct": 60},
            transition="tick",
        )

        service, payload = _light_call(fake_hass)
        assert service == "turn_on"
        assert payload == {
            "entity_id": ["light.a"],
            "brightness_pct": 60,
            "transition": 2,
        }

    def test_no_transition_key_when_zero(self, fake_hass, fake_store):
        applier, _ = _make_applier(fake_hass, fake_store, transition_sec=0)

        applier.turn_on(["light.a"], {"entity_id": ["light.a"]}, transition="tick")

        _, payload = _light_call(fake_hass)
        assert "transition" not in payload

    def test_marks_controlled_and_records_expected(self, fake_hass, fake_store):
        applier, state_ctrl = _make_applier(fake_hass, fake_store)

        applier.turn_on(
            ["light.a", "light.b"],
            {"entity_id": ["light.a", "light.b"]},
            transition="tick",
            brightness_pct=40,
            kelvin=2500,
        )

        assert state_ctrl.get_lights_we_control() == {"light.a", "light.b"}
        for lid in ("light.a", "light.b"):
            expected = state_ctrl.get_expected_state(lid)
            assert expected["on"] is True
            assert expected["brightness_pct"] == 40
            assert expected["kelvin"] == 2500

    def test_unset_values_are_not_expected(self, fake_hass, fake_store):
        """Attributes we don't control stay None so detection skips them."""
        applier, state_ctrl = _make_applier(fake_hass, fake_store)

        applier.turn_on(["light.a"], {"entity_id": ["light.a"]}, transition="tick")

        expected = state_ctrl.get_expected_state("light.a")
        assert expected["brightness_pct"] is None
        assert expected["kelvin"] is None


class TestTurnOff:
    """Turning off must release the lights and expect them off."""

    def test_calls_service_with_transition(self, fake_hass, fake_store):
        applier, _ = _make_applier(fake_hass, fake_store)

        applier.turn_off(["light.a"], transition="mode")

        service, payload = _light_call(fake_hass)
        assert service == "turn_off"
        assert payload == {"entity_id": ["light.a"], "transition": 2}

    def test_releases_control_and_records_expected_off(self, fake_hass, fake_store):
        applier, state_ctrl = _make_applier(fake_hass, fake_store)
        state_ctrl.mark_controlled(["light.a", "light.b"])

        applier.turn_off(["light.a", "light.b"], transition="tick")

        assert state_ctrl.get_lights_we_control() == set()
        for lid in ("light.a", "light.b"):
            assert state_ctrl.get_expected_state(lid)["on"] is False


class TestMarkApplied:
    """The commanded lights are exempted from detection while in flight."""

    def test_turn_on_marks_the_commanded_lights(self, fake_hass, fake_store):
        marked: list[list[str]] = []
        applier, _ = _make_applier(
            fake_hass, fake_store, mark_applied=lambda lights: marked.append(lights)
        )

        applier.turn_on(
            ["light.a", "light.b"],
            {"entity_id": ["light.a", "light.b"]},
            transition="tick",
        )

        assert marked == [["light.a", "light.b"]]

    def test_turn_off_marks_the_commanded_lights(self, fake_hass, fake_store):
        marked: list[list[str]] = []
        applier, _ = _make_applier(
            fake_hass, fake_store, mark_applied=lambda lights: marked.append(lights)
        )

        applier.turn_off(["light.a"], transition="tick")

        assert marked == [["light.a"]]

    def test_no_mark_applied_observer_is_safe(self, fake_hass, fake_store):
        """Without an observer, switching still works."""
        applier, state_ctrl = _make_applier(fake_hass, fake_store)

        applier.turn_on(["light.a"], {"entity_id": ["light.a"]}, transition="tick")

        assert state_ctrl.get_expected_state("light.a")["on"] is True

    def test_mark_applied_observer_raising_does_not_break_switching(
        self, fake_hass, fake_store
    ):
        def _raise(_lights: list[str]) -> None:
            raise RuntimeError("boom")

        applier, state_ctrl = _make_applier(
            fake_hass, fake_store, mark_applied=_raise
        )

        applier.turn_on(["light.a"], {"entity_id": ["light.a"]}, transition="tick")

        assert state_ctrl.get_expected_state("light.a")["on"] is True


class TestTransitionContext:
    """The transition context is passed through to the resolver."""

    @pytest.mark.parametrize("context", ["tick", "initial", "mode"])
    def test_context_forwarded(self, fake_hass, fake_store, context):
        seen: list[str] = []
        state_ctrl = StateController(fake_hass, "test_entry", "Test")
        state_ctrl._store = fake_store
        applier = LightApplier(
            fake_hass, state_ctrl, lambda ctx: seen.append(ctx) or 0, "Test"
        )

        applier.turn_on(["light.a"], {"entity_id": ["light.a"]}, transition=context)
        applier.turn_off(["light.a"], transition=context)

        assert seen == [context, context]
