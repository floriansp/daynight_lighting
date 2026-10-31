"""Tests for event-driven external control detection.

An external intervention (scene, manual dimmer, other automation) is detected
by comparing a light's reported state to the persisted expected state. The
result is written per light into ``held_lights`` with the ``"detected"``
reason, so the day/night automation leaves that light alone until the hold is
released or the phase changes.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from custom_components.daynight_lighting.const import DOMAIN, MODE_DAY, MODE_NIGHT
from custom_components.daynight_lighting.manual_control import ManualControlDetector
from custom_components.daynight_lighting.state_controller import (
    HOLD_REASON_DETECTED,
)
from custom_components.daynight_lighting.switch import DayNightLightingSwitch

from tests.conftest import FakeToggle, FakeState


class MockEvent:
    """Mock state change event."""

    def __init__(self, entity_id: str, new_state: FakeState | None = None) -> None:
        self.data = {"entity_id": entity_id, "new_state": new_state}


def _make_switch_with_mocks(
    fake_hass,
    fake_store,
    options: dict[str, Any] | None = None,
    day_mode: bool = True,
) -> tuple[DayNightLightingSwitch, FakeToggle, FakeToggle]:
    """Create a switch with mocked dependencies for event-driven testing."""
    opts = {
        "instance_name": "Test",
        "lights": ["light.a", "light.b"],
        "light_sensor": "sensor.lux",
        "motion_sensor": "binary_sensor.motion",
        "night_mode_start": "sun_below_horizon",
        "lux_on": 10.0,
        "lux_off": 100.0,
        "day_min_brightness": 10,
        "day_max_brightness": 100,
        "night_brightness": 80,
        "circadian_enabled": True,
        "circadian_min_kelvin": 2700,
        "circadian_max_kelvin": 5500,
        "motion_off_delay_min": 5,
        "on_enter_night": "leave",
    }
    opts.update(options or {})

    entry = SimpleNamespace(
        entry_id="test_entry",
        options=opts,
        data={"instance_name": "Test"},
    )

    # Auxiliary switches
    ctrl_brightness = FakeToggle(
        _attr_is_on=True,
        async_write_ha_state=lambda: None,
    )
    ctrl_color = FakeToggle(
        _attr_is_on=True,
        async_write_ha_state=lambda: None,
    )

    # Wire up hass.data[DOMAIN][entry_id]
    fake_hass.data = {
        DOMAIN: {
            entry.entry_id: {
                "control_brightness_switch": ctrl_brightness,
                "control_color_switch": ctrl_color,
            }
        }
    }

    # Sun state
    sun_state = "above_horizon" if day_mode else "below_horizon"
    fake_hass.states.set(
        "sun.sun",
        FakeState(
            state=sun_state,
            attributes={
                "elevation": 30.0 if day_mode else -10.0,
                "next_rising": "2026-06-16T05:15:00+00:00",
            },
        ),
    )

    # LUX sensor
    fake_hass.states.set("sensor.lux", FakeState(state="50.0", attributes={}))

    # Create switch
    switch = DayNightLightingSwitch(entry, "Test")
    switch.hass = fake_hass
    switch.async_write_ha_state = lambda: None
    switch._attr_is_on = True

    # Inject state controller with fake store
    from custom_components.daynight_lighting.state_controller import StateController

    state_ctrl = StateController(fake_hass, entry.entry_id, "Test")
    state_ctrl._store = fake_store
    switch._state_ctrl_instance = state_ctrl

    return switch, ctrl_brightness, ctrl_color


class TestManualControlDetector:
    """Unit tests for the detector's tolerances and grace period."""

    def test_day_mode_with_sensor_tolerances(self):
        """Day mode with LUX sensor uses higher tolerances."""
        tol = ManualControlDetector.get_tolerances_for_mode(MODE_DAY, has_lux_sensor=True)
        assert tol == (10, 300)  # brightness, kelvin

    def test_day_mode_without_sensor_tolerances(self):
        """Day mode without LUX sensor uses lower tolerances."""
        tol = ManualControlDetector.get_tolerances_for_mode(MODE_DAY, has_lux_sensor=False)
        assert tol == (5, 200)

    def test_night_mode_tolerances(self):
        """Night mode uses medium tolerances."""
        tol = ManualControlDetector.get_tolerances_for_mode(MODE_NIGHT, has_lux_sensor=False)
        assert tol == (5, 200)

    def test_sleep_mode_tolerances(self):
        """Sleep mode accounts for gradual transitions."""
        tol = ManualControlDetector.get_tolerances_for_mode("sleep", has_lux_sensor=False)
        assert tol[0] >= 5  # brightness tolerance

    def test_wakeup_mode_tolerances(self):
        """Wake-up mode accounts for gradual transitions."""
        tol = ManualControlDetector.get_tolerances_for_mode("wakeup", has_lux_sensor=False)
        assert tol[0] >= 5  # brightness tolerance

    def test_grace_period_duration_is_5_seconds(self):
        """Grace period is 5 seconds."""
        assert ManualControlDetector.DEFAULT_GRACE_PERIOD_SEC == 5


class TestCheckExternalControl:
    """Real-world detection scenarios (detector level)."""

    @pytest.mark.asyncio
    async def test_external_brightness_change_detected(self, fake_hass, fake_store):
        """Detection triggers when brightness changes beyond tolerance."""
        switch, *_ = _make_switch_with_mocks(fake_hass, fake_store)

        # We set light to 50%
        switch._state_ctrl.set_expected_state("light.a", on=True, brightness_pct=50)
        switch._manual_control_detector._last_applied_time.clear()

        # External scene changes brightness to 80% (>10% tolerance for day mode)
        fake_hass.states.set(
            "light.a",
            FakeState(state="on", attributes={"brightness": 204}),  # 80%
        )

        external = switch._manual_control_detector.check_external_control(
            fake_hass,
            ["light.a"],
            switch._state_ctrl,
            check_brightness=True,
            check_color=False,
            brightness_tolerance_pct=10,
            kelvin_tolerance=200,
        )

        assert "light.a" in external

    @pytest.mark.asyncio
    async def test_matching_values_not_detected(self, fake_hass, fake_store):
        """No detection when values match expected (within tolerance)."""
        switch, *_ = _make_switch_with_mocks(fake_hass, fake_store)

        switch._state_ctrl.set_expected_state("light.a", on=True, brightness_pct=50)
        switch._manual_control_detector._last_applied_time.clear()

        fake_hass.states.set(
            "light.a",
            FakeState(state="on", attributes={"brightness": 132}),  # ~52%
        )

        external = switch._manual_control_detector.check_external_control(
            fake_hass,
            ["light.a"],
            switch._state_ctrl,
            check_brightness=True,
            check_color=False,
            brightness_tolerance_pct=10,
            kelvin_tolerance=200,
        )

        assert "light.a" not in external

    @pytest.mark.asyncio
    async def test_light_turned_off_externally_detected(self, fake_hass, fake_store):
        """Detection triggers when light is turned off externally."""
        switch, *_ = _make_switch_with_mocks(fake_hass, fake_store)

        switch._state_ctrl.set_expected_state("light.a", on=True, brightness_pct=50)
        switch._manual_control_detector._last_applied_time.clear()

        fake_hass.states.set("light.a", FakeState(state="off", attributes={}))

        external = switch._manual_control_detector.check_external_control(
            fake_hass,
            ["light.a"],
            switch._state_ctrl,
            check_brightness=True,
            check_color=False,
        )

        assert "light.a" in external

    @pytest.mark.asyncio
    async def test_light_turned_on_externally_detected(self, fake_hass, fake_store):
        """Detection triggers when light is turned on externally (expected OFF)."""
        switch, *_ = _make_switch_with_mocks(fake_hass, fake_store)

        switch._state_ctrl.set_expected_state("light.a", on=False)
        switch._manual_control_detector._last_applied_time.clear()

        fake_hass.states.set(
            "light.a",
            FakeState(state="on", attributes={"brightness": 128}),
        )

        external = switch._manual_control_detector.check_external_control(
            fake_hass,
            ["light.a"],
            switch._state_ctrl,
            check_brightness=True,
            check_color=False,
        )

        assert "light.a" in external

    @pytest.mark.asyncio
    async def test_service_turn_off_not_detected_as_external(self, fake_hass, fake_store):
        """daynight_lighting.turn_off prepares expected OFF → no false detection."""
        switch, *_ = _make_switch_with_mocks(fake_hass, fake_store)

        switch._state_ctrl.set_expected_state("light.a", on=True, brightness_pct=50)
        switch._manual_control_detector._last_applied_time.clear()

        # Service prepares the turn-off, then the light reports OFF
        switch.prepare_lights_turn_off_by_service(["light.a"])
        fake_hass.states.set("light.a", FakeState(state="off", attributes={}))

        external = switch._manual_control_detector.check_external_control(
            fake_hass,
            ["light.a"],
            switch._state_ctrl,
            check_brightness=True,
            check_color=False,
        )

        assert external == []
        # Expected state is persisted as OFF, so detection stays quiet after
        # the grace period expires too
        switch._manual_control_detector._last_applied_time.clear()
        assert switch._manual_control_detector.check_external_control(
            fake_hass,
            ["light.a"],
            switch._state_ctrl,
            check_brightness=True,
            check_color=False,
        ) == []

    @pytest.mark.asyncio
    async def test_service_turn_on_not_detected_as_external(self, fake_hass, fake_store):
        """daynight_lighting.turn_on prepares our values → no false detection."""
        switch, *_ = _make_switch_with_mocks(fake_hass, fake_store)

        switch._state_ctrl.set_expected_state("light.a", on=False)
        switch._manual_control_detector._last_applied_time.clear()

        switch.prepare_lights_applied_by_service(
            ["light.a"], on=True, brightness_pct=60, kelvin=4000
        )
        fake_hass.states.set(
            "light.a",
            FakeState(state="on", attributes={"brightness": 153, "color_temp": 250}),
        )

        def _check() -> list[str]:
            return switch._manual_control_detector.check_external_control(
                fake_hass,
                ["light.a"],
                switch._state_ctrl,
                check_brightness=True,
                check_color=True,
            )

        assert _check() == []
        switch._manual_control_detector._last_applied_time.clear()
        assert _check() == []


class TestEventDrivenHold:
    """A detected intervention is written into held_lights (reason=detected)."""

    @staticmethod
    def _capture_callback(switch, monkeypatch):
        """Start listeners and capture the light state-change callback."""
        captured = {}

        def _track(hass, entities, callback):
            if "light.a" in entities:
                captured["cb"] = callback
            return lambda: None

        monkeypatch.setattr(
            "custom_components.daynight_lighting.switch"
            ".async_track_state_change_event",
            _track,
        )
        monkeypatch.setattr(
            "custom_components.daynight_lighting.switch"
            ".async_track_time_change",
            lambda *a, **kw: (lambda: None),
        )
        switch._start_listeners()
        return captured.get("cb")

    @staticmethod
    def _reset_expected(switch):
        """Drop the expected states the initial tick applied and any grace period."""
        for lid in ("light.a", "light.b"):
            switch._state_ctrl.clear_expected_state(lid)
        switch._manual_control_detector._last_applied_time.clear()

    def test_external_change_holds_the_light(self, fake_hass, fake_store, monkeypatch):
        """A foreign brightness change holds the light as 'detected'."""
        switch, *_ = _make_switch_with_mocks(fake_hass, fake_store)
        callback = self._capture_callback(switch, monkeypatch)
        assert callback is not None

        self._reset_expected(switch)
        switch._state_ctrl.set_expected_state("light.a", on=True, brightness_pct=50)

        new_state = FakeState(state="on", attributes={"brightness": 204})
        fake_hass.states.set("light.a", new_state)
        callback(MockEvent("light.a", new_state))

        assert switch._state_ctrl.is_held("light.a")
        assert switch._state_ctrl.get_hold_reason("light.a") == HOLD_REASON_DETECTED

    def test_matching_values_do_not_hold(self, fake_hass, fake_store, monkeypatch):
        """Our own values within tolerance do not create a hold."""
        switch, *_ = _make_switch_with_mocks(fake_hass, fake_store)
        callback = self._capture_callback(switch, monkeypatch)
        assert callback is not None

        self._reset_expected(switch)
        switch._state_ctrl.set_expected_state("light.a", on=True, brightness_pct=50)

        new_state = FakeState(state="on", attributes={"brightness": 128})
        fake_hass.states.set("light.a", new_state)
        callback(MockEvent("light.a", new_state))

        assert not switch._state_ctrl.is_held("light.a")

    def test_detection_skipped_when_switch_off(self, fake_hass, fake_store, monkeypatch):
        """No detection when the main switch is off."""
        switch, *_ = _make_switch_with_mocks(fake_hass, fake_store)
        switch._attr_is_on = False
        switch._state_ctrl.set_expected_state("light.a", on=True, brightness_pct=50)
        switch._manual_control_detector._last_applied_time.clear()

        callback = self._capture_callback(switch, monkeypatch)
        assert callback is not None

        new_state = FakeState(state="on", attributes={"brightness": 204})
        fake_hass.states.set("light.a", new_state)
        callback(MockEvent("light.a", new_state))

        assert not switch._state_ctrl.is_held("light.a")

    def test_detection_skipped_during_grace_period(self, fake_hass, fake_store, monkeypatch):
        """No detection during the grace period after we applied values."""
        switch, *_ = _make_switch_with_mocks(fake_hass, fake_store)
        callback = self._capture_callback(switch, monkeypatch)
        assert callback is not None

        self._reset_expected(switch)
        switch._manual_control_detector.mark_applied(["light.a"])
        switch._state_ctrl.set_expected_state("light.a", on=True, brightness_pct=50)

        new_state = FakeState(state="on", attributes={"brightness": 204})
        fake_hass.states.set("light.a", new_state)
        callback(MockEvent("light.a", new_state))

        assert not switch._state_ctrl.is_held("light.a")

    def test_detection_skipped_without_expected_state(self, fake_hass, fake_store, monkeypatch):
        """No detection if we haven't applied values yet (no expected state)."""
        switch, *_ = _make_switch_with_mocks(fake_hass, fake_store)
        callback = self._capture_callback(switch, monkeypatch)
        assert callback is not None

        self._reset_expected(switch)

        new_state = FakeState(state="on", attributes={"brightness": 204})
        fake_hass.states.set("light.a", new_state)
        callback(MockEvent("light.a", new_state))

        assert not switch._state_ctrl.is_held("light.a")


class TestTickMarksLightsApplied:
    """The normal tick exempts its own commands from detection.

    light.turn_on is async, so the state-change events of our own command can
    arrive while the light is still transitioning. The mode handlers must mark
    the lights they just commanded as "applied" so detection lets that pass.
    """

    def test_day_tick_marks_the_commanded_lights(self, make_switch, fake_hass):
        switch, *_ = make_switch(day_mode=True)
        fake_hass.states.set("sensor.lux", FakeState(state="50"))

        switch._get_mode_handler(MODE_DAY).tick()

        detector = switch._manual_control_detector
        assert "light.a" in detector._last_applied_time
        assert "light.b" in detector._last_applied_time

    def test_skipped_day_tick_marks_nothing(self, make_switch, fake_hass):
        """A tick that sends no command must not open a grace period."""
        switch, *_ = make_switch(day_mode=True)
        fake_hass.states.set("sensor.lux", FakeState(state="50"))

        day = switch._get_mode_handler(MODE_DAY)
        day.tick()  # first apply: sends brightness
        detector = switch._manual_control_detector
        detector._last_applied_time.clear()

        day.tick()  # same target: nothing sent

        assert detector._last_applied_time == {}
