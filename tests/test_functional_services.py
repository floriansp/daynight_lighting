"""Functional tests: Service API methods on DayNightLightingSwitch."""

from __future__ import annotations
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from custom_components.daynight_lighting.const import MODE_NIGHT
from custom_components.daynight_lighting.services import async_turn_off, async_turn_on

from tests.conftest import FakeState


class TestRecordLightsTurnedOnByService:
    """Tests for record_lights_turned_on_by_service."""

    def test_marks_controlled_and_holds(self, make_switch, fake_hass):
        """hold=True → lights marked as controlled and held."""
        switch, *_ = make_switch(day_mode=False)

        switch.record_lights_turned_on_by_service(["light.a"])

        assert switch._state_ctrl.is_controlled_by_us("light.a")
        assert switch._state_ctrl.is_held("light.a")

    def test_hold_false_does_not_hold(self, make_switch, fake_hass):
        """hold=False → controlled remains, but no hold is recorded."""
        switch, *_ = make_switch(day_mode=False)

        switch.record_lights_turned_on_by_service(["light.a"], hold=False)

        assert switch._state_ctrl.is_controlled_by_us("light.a")
        assert not switch._state_ctrl.is_held("light.a")

    def test_record_turn_on_cancels_pending_off_timer(self, make_switch, fake_hass):
        """A turn_on cancels a pending night motion-off timer.

        Otherwise the timer can fire while ``light.turn_on`` awaits and switch
        the light straight back off after the visitor turned it on.
        """
        switch, *_ = make_switch(day_mode=False)
        switch._state_ctrl.mark_controlled(["light.a", "light.b"])

        switch._handle_motion_off()
        assert len(switch._action_scheduler._entries) == 1

        switch.record_lights_turned_on_by_service(["light.a", "light.b"])

        assert len(switch._action_scheduler._entries) == 0

    def test_record_turn_on_without_hold_keeps_off_timer(self, make_switch, fake_hass):
        """hold=False does not cancel a pending motion-off timer."""
        switch, *_ = make_switch(day_mode=False)
        switch._state_ctrl.mark_controlled(["light.a", "light.b"])
        switch._handle_motion_off()
        assert len(switch._action_scheduler._entries) == 1

        switch.record_lights_turned_on_by_service(["light.a", "light.b"], hold=False)

        assert len(switch._action_scheduler._entries) == 1


class TestHoldSurvivesOnOffOn:
    """Kitchen bug: on/off combos must leave the light held on, not off."""

    def test_on_off_on_then_motion_off_stays_on(self, make_switch, fake_hass):
        """A visitor's on→off→on sequence ends held on and protected.

        Regression: the final turn_on recorded its hold only after the light
        call, so a pending motion-off timer could fire first and leave the
        light off despite the hold.
        """
        switch, *_ = make_switch(day_mode=False)
        fake_hass.states.set("binary_sensor.motion", FakeState(state="on"))
        switch._handle_motion_on()

        switch.record_lights_turned_on_by_service(["light.a", "light.b"])
        switch.record_lights_turned_off_by_service(["light.a", "light.b"])
        switch.record_lights_turned_on_by_service(["light.a", "light.b"])

        assert switch._state_ctrl.get_held_lights() == {"light.a", "light.b"}

        # Motion clears → the off timer's result must be empty: held lights stay on.
        fake_hass.states.set("binary_sensor.motion", FakeState(state="off"))
        result, _ = switch._get_mode_handler(MODE_NIGHT)._off_timer_result()
        assert result == []


class TestRecordLightsTurnedOffByService:
    """Tests for record_lights_turned_off_by_service."""

    def test_unmarks_controlled_and_clears_applied(
        self, make_switch, fake_hass
    ):
        """Turn off via service → state cleaned up."""
        switch, *_ = make_switch(day_mode=False)
        switch._state_ctrl.mark_controlled(["light.a", "light.b"])
        switch._manual_control_detector.mark_applied(["light.a", "light.b"])

        switch.record_lights_turned_off_by_service(["light.a"])

        assert not switch._state_ctrl.is_controlled_by_us("light.a")
        assert switch._state_ctrl.is_controlled_by_us("light.b")

    def test_record_turn_off_without_hold_does_not_hold(
        self, make_switch, fake_hass
    ):
        """hold=False switches the lights off without holding them."""
        switch, *_ = make_switch(day_mode=False)
        switch._state_ctrl.mark_controlled(["light.a"])

        switch.record_lights_turned_off_by_service(["light.a"], hold=False)

        assert not switch._state_ctrl.is_controlled_by_us("light.a")
        assert not switch._state_ctrl.is_held("light.a")


class TestHoldAllLights:
    """Tests for hold_all_lights — the bulk replacement for the manual switch."""

    def test_hold_all_registers_every_light(self, make_switch, fake_hass):
        switch, *_ = make_switch(day_mode=False)

        switch.hold_all_lights()

        assert switch._state_ctrl.get_held_lights() == {"light.a", "light.b"}
        assert switch._state_ctrl.get_hold_reason("light.a") == "service"


class TestGetDesiredTurnOnParams:
    """Tests for get_desired_turn_on_params."""

    def test_day_mode_returns_lux_brightness(self, make_switch, fake_hass):
        """Day mode → LUX-based brightness + circadian kelvin."""
        switch, *_ = make_switch(day_mode=True)
        fake_hass.states.set("sensor.lux", FakeState(state="50"))

        params = switch.get_desired_turn_on_params()

        assert params["brightness_pct"] == 60
        assert "color_temp_kelvin" in params

    def test_night_mode_returns_night_brightness(
        self, make_switch, fake_hass
    ):
        """Night mode → configured night brightness + circadian kelvin."""
        switch, *_ = make_switch(day_mode=False)

        params = switch.get_desired_turn_on_params()

        assert params["brightness_pct"] == 80
        assert "color_temp_kelvin" in params

    def test_control_switches_respected(self, make_switch, fake_hass):
        """Control Brightness OFF → no brightness in params."""
        switch, ctrl_brightness, ctrl_color = make_switch(day_mode=False)
        ctrl_brightness._attr_is_on = False
        ctrl_color._attr_is_on = False

        params = switch.get_desired_turn_on_params()

        assert "brightness_pct" not in params
        assert "color_temp_kelvin" not in params

    def test_force_on_bright_room_turns_on_at_day_max(self, make_switch, fake_hass):
        """force_on lifts a 0 (off) brightness to day_max so the light turns on.

        Regression for the kitchen bug: with ``day_min_brightness`` 0 and LUX
        at/above ``lux_off`` a wall-button ``turn_on`` used to compute 0 and
        leave the light off.
        """
        switch, *_ = make_switch(
            options={
                "day_min_brightness": 0,
                "lux_off": 55,
                "day_max_brightness": 45,
            },
            day_mode=True,
        )
        fake_hass.states.set("sensor.lux", FakeState(state="80"))

        assert switch.get_desired_turn_on_params()["brightness_pct"] == 0
        assert switch.get_desired_turn_on_params(force_on=True)["brightness_pct"] == 45

    def test_force_on_keeps_positive_brightness(self, make_switch, fake_hass):
        """force_on does not override a positive LUX-derived brightness."""
        switch, *_ = make_switch(
            options={
                "day_min_brightness": 0,
                "lux_off": 55,
                "day_max_brightness": 45,
            },
            day_mode=True,
        )
        fake_hass.states.set("sensor.lux", FakeState(state="20"))

        assert switch.get_desired_turn_on_params()["brightness_pct"] == 35
        assert switch.get_desired_turn_on_params(force_on=True)["brightness_pct"] == 35


class TestTurnOnAfterHoldOff:
    """Kitchen bug: a wall-button OFF holds the light, ON must still switch it on."""

    def test_turn_on_after_hold_off_turns_on_at_day_max(self, make_switch, fake_hass):
        """After ``turn_off`` (hold) in a bright room, ``turn_on`` (hold) turns on.

        Regression: ``get_desired_turn_on_params`` returned 0 for a bright room
        with ``day_min_brightness`` 0, so the wall button switched the light on
        at 0 % — it stayed off despite the hold being overwritten.
        """
        switch, *_ = make_switch(
            options={
                "day_min_brightness": 0,
                "lux_off": 55,
                "day_max_brightness": 45,
            },
            day_mode=True,
        )
        fake_hass.states.set("sensor.lux", FakeState(state="80"))

        # turn off via taster (hold=true)
        switch.prepare_lights_turn_off_by_service(["light.a"])
        switch.record_lights_turned_off_by_service(["light.a"], hold=True)
        assert switch._state_ctrl.is_held("light.a")

        # turn on via taster (hold=true)
        params = switch.get_desired_turn_on_params(force_on=True)
        stays_on = params.get("brightness_pct", 0) != 0
        switch.prepare_lights_applied_by_service(
            ["light.a"],
            on=stays_on,
            brightness_pct=params.get("brightness_pct") if stays_on else None,
            kelvin=params.get("color_temp_kelvin") if stays_on else None,
        )
        switch.record_lights_turned_on_by_service(["light.a"], hold=True)

        assert params["brightness_pct"] == 45
        expected = switch._state_ctrl.get_expected_state("light.a")
        assert expected["on"] is True
        assert expected["brightness_pct"] == 45
        assert switch._state_ctrl.is_held("light.a")


@pytest.mark.parametrize("duration", [0, 5, 12])
@pytest.mark.parametrize("on", [True, False])
def test_service_preparation_protects_the_commanded_transition(
    make_switch, duration, on
):
    """Direct service commands share the detector's transition-aware grace."""
    switch, *_ = make_switch()
    detector = switch._manual_control_detector
    start = datetime(2026, 11, 19, tzinfo=timezone.utc)
    with patch("custom_components.daynight_lighting.manual_control.datetime") as clock:
        clock.now.return_value = start
        if on:
            switch.prepare_lights_applied_by_service(
                ["light.a"], on=True, brightness_pct=80,
                transition_seconds=duration,
            )
        else:
            switch.prepare_lights_turn_off_by_service(
                ["light.a"], transition_seconds=duration
            )
        clock.now.return_value = start + timedelta(seconds=duration + 4.999)
        assert detector.is_in_grace_period("light.a")
        assert not detector.is_in_grace_period("light.b")
        clock.now.return_value = start + timedelta(seconds=duration + 5)
        assert not detector.is_in_grace_period("light.a")


@pytest.mark.parametrize("command", ["turn_on", "turn_on_explicit", "turn_off"])
@pytest.mark.parametrize(
    ("transition", "duration", "error"),
    [
        ("5", 5, None),
        ("2.5", 2.5, None),
        (None, 0, None),
        ("{{ transition }}", None, ValueError),
        (timedelta(seconds=5), None, TypeError),
    ],
)
@pytest.mark.asyncio
async def test_service_transition_is_numeric_before_marking(
    make_switch, fake_hass, command, transition, duration, error
):
    """Coerce service ramps or reject them before they can poison detection."""
    switch, *_ = make_switch(day_mode=False)
    detector = switch._manual_control_detector
    fake_hass.services.async_call = AsyncMock()
    data = {"entity_id": "switch.test", "transition": transition}
    if command == "turn_on_explicit":
        data["brightness_pct"] = 80
    call = SimpleNamespace(hass=fake_hass, data=data)
    handler = async_turn_off if command == "turn_off" else async_turn_on
    start = datetime(2026, 11, 19, tzinfo=timezone.utc)
    with (
        patch(
            "custom_components.daynight_lighting.services."
            "_get_config_and_lights_for_entity_id",
            return_value=(SimpleNamespace(entry_id="test_entry"), ["light.a"]),
        ),
        patch(
            "custom_components.daynight_lighting.services.instance_controller",
            return_value=switch,
        ),
        patch("custom_components.daynight_lighting.manual_control.datetime") as clock,
    ):
        clock.now.return_value = start
        if error is not None:
            with pytest.raises(error):
                await handler(call)
            fake_hass.services.async_call.assert_not_called()
            assert not detector.is_in_grace_period("light.a")
            assert "light.a" not in detector._last_applied_time
            assert "light.a" not in detector._transition_seconds
            return
        await handler(call)
        # Only the detector's copy is coerced; preserve service passthrough.
        assert fake_hass.services.async_call.call_args.args[2]["transition"] == transition
        clock.now.return_value = start + timedelta(seconds=duration + 4.999)
        assert detector.is_in_grace_period("light.a")
        assert not detector.is_in_grace_period("light.b")
        clock.now.return_value = start + timedelta(seconds=duration + 5)
        assert not detector.is_in_grace_period("light.a")
        assert "light.a" not in detector._last_applied_time
        assert "light.a" not in detector._transition_seconds
