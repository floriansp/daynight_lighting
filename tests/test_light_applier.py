"""Tests for LightApplier — the single entry point for switching lights."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from custom_components.daynight_lighting.light_applier import LightApplier
from custom_components.daynight_lighting.manual_control import (
    ExpectedState,
    ManualControlDetector,
)
from custom_components.daynight_lighting.state_controller import StateController

from tests.conftest import FakeState


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
        fake_hass.states.set("light.a", FakeState(state="on"))
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
        marked: list[tuple[list[str], float]] = []
        applier, _ = _make_applier(
            fake_hass, fake_store, mark_applied=lambda lights, seconds: marked.append((lights, seconds))
        )

        applier.turn_on(
            ["light.a", "light.b"],
            {"entity_id": ["light.a", "light.b"]},
            transition="tick",
        )

        assert marked == [(["light.a", "light.b"], 2)]

    def test_turn_off_marks_the_commanded_lights(self, fake_hass, fake_store):
        fake_hass.states.set("light.a", FakeState(state="on"))
        marked: list[tuple[list[str], float]] = []
        applier, _ = _make_applier(
            fake_hass, fake_store, mark_applied=lambda lights, seconds: marked.append((lights, seconds))
        )

        applier.turn_off(["light.a"], transition="tick")

        assert marked == [(["light.a"], 2)]

    def test_no_mark_applied_observer_is_safe(self, fake_hass, fake_store):
        """Without an observer, switching still works."""
        applier, state_ctrl = _make_applier(fake_hass, fake_store)

        applier.turn_on(["light.a"], {"entity_id": ["light.a"]}, transition="tick")

        assert state_ctrl.get_expected_state("light.a")["on"] is True

    def test_mark_applied_observer_raising_does_not_break_switching(
        self, fake_hass, fake_store
    ):
        def _raise(_lights: list[str], _seconds: float) -> None:
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
        fake_hass.states.set("light.a", FakeState(state="on"))
        seen: list[str] = []
        state_ctrl = StateController(fake_hass, "test_entry", "Test")
        state_ctrl._store = fake_store
        applier = LightApplier(
            fake_hass, state_ctrl, lambda ctx: seen.append(ctx) or 0, "Test"
        )

        applier.turn_on(["light.a"], {"entity_id": ["light.a"]}, transition=context)
        applier.turn_off(["light.a"], transition=context)

        assert seen == [context, context]


def _on(fake_hass, light: str, brightness_pct: int) -> None:
    """Show *light* as on at *brightness_pct* percent."""
    fake_hass.states.set(
        light,
        FakeState(state="on", attributes={"brightness": round(brightness_pct * 255 / 100)}),
    )


class TestStepBrightness:
    """A wall-button step moves each light and never walks it below the floor."""

    def test_steps_an_on_light_and_records_the_target(self, fake_hass, fake_store):
        applier, state_ctrl = _make_applier(fake_hass, fake_store)
        _on(fake_hass, "light.a", 50)

        applier.step_brightness(["light.a"], 10, floor=5)

        _, payload = _light_call(fake_hass)
        assert payload["brightness_pct"] == 60
        assert state_ctrl.get_expected_state("light.a")["brightness_pct"] == 60

    def test_never_goes_below_the_floor(self, fake_hass, fake_store):
        applier, _ = _make_applier(fake_hass, fake_store)
        _on(fake_hass, "light.a", 8)

        applier.step_brightness(["light.a"], -30, floor=5)

        _, payload = _light_call(fake_hass)
        assert payload["brightness_pct"] == 5

    def test_never_goes_above_100(self, fake_hass, fake_store):
        applier, _ = _make_applier(fake_hass, fake_store)
        _on(fake_hass, "light.a", 95)

        applier.step_brightness(["light.a"], 20, floor=5)

        _, payload = _light_call(fake_hass)
        assert payload["brightness_pct"] == 100

    def test_an_off_light_stays_off_when_dimming(self, fake_hass, fake_store):
        applier, _ = _make_applier(fake_hass, fake_store)
        fake_hass.states.set("light.a", FakeState(state="off"))

        applier.step_brightness(["light.a"], -10, floor=5)

        fake_hass.services.async_call.assert_not_called()

    def test_an_off_light_comes_on_at_the_step_when_brightening(
        self, fake_hass, fake_store
    ):
        applier, _ = _make_applier(fake_hass, fake_store)
        fake_hass.states.set("light.a", FakeState(state="off"))

        applier.step_brightness(["light.a"], 10, floor=5)

        _, payload = _light_call(fake_hass)
        assert payload["brightness_pct"] == 10


def test_turn_off_skips_lights_that_are_already_off(fake_hass, fake_store) -> None:
    """Only real off commands renew grace; all targets retain off bookkeeping."""
    lights = [
        "light.on",
        "light.off",
        "light.unknown",
        "light.unavailable",
        "light.missing",
        "light.also_on",
    ]
    for light, state in [
        ("light.on", "on"),
        ("light.off", "off"),
        ("light.unknown", "unknown"),
        ("light.unavailable", "unavailable"),
        ("light.also_on", "on"),
    ]:
        fake_hass.states.set(light, FakeState(state=state))
    marked: list[tuple[list[str], float]] = []
    notified: list[ExpectedState] = []
    state_ctrl = StateController(fake_hass, "test_entry", "Test")
    state_ctrl._store = fake_store
    applier = LightApplier(
        fake_hass,
        state_ctrl,
        lambda _context: 2,
        on_applied=notified.append,
        mark_applied=lambda lights, seconds: marked.append((lights, seconds)),
    )
    state_ctrl.mark_controlled(lights)

    applier.turn_off(lights, transition="tick")

    fake_hass.services.async_call.assert_called_once_with(
        "light",
        "turn_off",
        {"entity_id": ["light.on", "light.also_on"], "transition": 2},
    )
    assert marked == [(["light.on", "light.also_on"], 2)]
    assert notified == [ExpectedState(on=False)]
    assert state_ctrl.get_lights_we_control() == set()
    for light in lights:
        assert state_ctrl.get_expected_state(light)["on"] is False
        fake_hass.states.set(light, FakeState(state="off"))
        # Stale bookkeeping must be corrected even without a service call.
        state_ctrl.set_expected_state(light, on=True)
    state_ctrl.mark_controlled(lights)

    applier.turn_off(lights, transition="tick")

    assert fake_hass.services.async_call.call_count == 1
    assert marked == [(["light.on", "light.also_on"], 2)]
    assert notified == [ExpectedState(on=False), ExpectedState(on=False)]
    assert state_ctrl.get_lights_we_control() == set()
    for light in lights:
        assert state_ctrl.get_expected_state(light)["on"] is False


@pytest.mark.parametrize("service", ["turn_on", "turn_off"])
@pytest.mark.parametrize("duration", [0, 5, 12])
def test_a_transition_extends_the_grace_period(
    fake_hass, fake_store, service, duration
):
    """Only commanded lights get the ramp duration plus five seconds (V31)."""
    detector = ManualControlDetector("Test")
    applier, _ = _make_applier(
        fake_hass, fake_store, duration, mark_applied=detector.mark_applied
    )
    fake_hass.states.set("light.a", FakeState(state="on"))
    fake_hass.states.set("light.off", FakeState(state="off"))
    start = datetime(2026, 11, 19, 22, 34, 55, tzinfo=timezone.utc)
    with patch("custom_components.daynight_lighting.manual_control.datetime") as clock:
        clock.now.return_value = start
        if service == "turn_on":
            applier.turn_on(
                ["light.a"], {"entity_id": ["light.a"]}, transition="initial"
            )
        else:
            applier.turn_off(["light.a", "light.off"], transition="mode")
        _, payload = _light_call(fake_hass)
        assert payload.get("transition", 0) == duration
        assert not detector.is_in_grace_period("light.b")
        assert not detector.is_in_grace_period("light.off")

        for seconds in sorted({4.999, 5, 5.1, duration + 4.999, duration + 5}):
            clock.now.return_value = start + timedelta(seconds=seconds)
            assert detector.is_in_grace_period("light.a") is (seconds < duration + 5)
            # A no-op OFF must not restart or lengthen an existing grace.
            if service == "turn_off":
                fake_hass.states.set("light.a", FakeState(state="off"))
                applier.turn_off(["light.a", "light.off"], transition="mode")
        assert fake_hass.services.async_call.call_count == 1
