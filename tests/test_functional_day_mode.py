"""Functional tests: Day-mode orchestration in DayNightLightingSwitch."""

from __future__ import annotations

from unittest.mock import Mock

from tests.conftest import FakeState


# Expected values with default options (lux_on=10, lux_off=100, day_min=10,
# day_max=100, circadian min=2700K max=5500K, sun elevation=30°):
#   lux=50 → brightness ~60%
#   elevation=30 → t=50/80=0.625 → kelvin=round(2700+2800*0.625) = 4450


class TestApplyDayMode:
    """Tests for _apply_day_mode (the core day-mode apply logic)."""

    def test_applies_brightness_and_color(self, make_switch, fake_hass):
        """LUX in range → brightness + circadian kelvin sent."""
        switch, *_ = make_switch(day_mode=True)
        fake_hass.states.set("sensor.lux", FakeState(state="50"))

        day_handler = switch._get_mode_handler("day")
        day_handler._apply_day_mode()

        calls = fake_hass.services.async_call.call_args_list
        assert len(calls) == 1
        _, _, payload = calls[0][0]
        assert payload["entity_id"] == ["light.a", "light.b"]
        assert payload["brightness_pct"] == 60
        assert payload["color_temp_kelvin"] == 4450

    def test_high_lux_min_zero_turns_off(self, make_switch, fake_hass):
        """LUX >= lux_off with day_min=0 → None brightness → lights off."""
        switch, *_ = make_switch(
            options={"day_min_brightness": 0}, day_mode=True
        )
        fake_hass.states.set("sensor.lux", FakeState(state="150"))

        day_handler = switch._get_mode_handler("day")
        day_handler._apply_day_mode()

        calls = fake_hass.services.async_call.call_args_list
        assert len(calls) == 1
        domain, service, data = calls[0][0]
        assert domain == "light"
        assert service == "turn_off"
        assert data == {"entity_id": ["light.a", "light.b"]}

    def test_high_lux_min_nonzero_keeps_brightness(self, make_switch, fake_hass):
        """LUX >= lux_off with day_min=10 → brightness=10."""
        switch, *_ = make_switch(day_mode=True)
        fake_hass.states.set("sensor.lux", FakeState(state="150"))

        day_handler = switch._get_mode_handler("day")
        day_handler._apply_day_mode()

        calls = fake_hass.services.async_call.call_args_list
        assert len(calls) == 1
        _, _, payload = calls[0][0]
        assert payload["brightness_pct"] == 10

    def test_lux_unavailable_skips(self, make_switch, fake_hass):
        """LUX sensor returns None (e.g. after restart) → no action."""
        switch, *_ = make_switch(day_mode=True)
        # No sensor.lux state set → get_lux() returns None

        day_handler = switch._get_mode_handler("day")
        day_handler._apply_day_mode()

        fake_hass.services.async_call.assert_not_called()

    def test_control_brightness_off_no_brightness_in_payload(
        self, make_switch, fake_hass
    ):
        """Control Brightness OFF → payload has color but not brightness."""
        switch, ctrl_brightness, _ = make_switch(day_mode=True)
        ctrl_brightness._attr_is_on = False
        fake_hass.states.set("sensor.lux", FakeState(state="50"))

        day_handler = switch._get_mode_handler("day")
        day_handler._apply_day_mode()

        calls = fake_hass.services.async_call.call_args_list
        assert len(calls) == 1
        _, _, payload = calls[0][0]
        assert "brightness_pct" not in payload
        assert "color_temp_kelvin" in payload

    def test_control_color_off_no_color_in_payload(
        self, make_switch, fake_hass
    ):
        """Control Color OFF → payload has brightness but not color."""
        switch, _, ctrl_color = make_switch(day_mode=True)
        ctrl_color._attr_is_on = False
        fake_hass.states.set("sensor.lux", FakeState(state="50"))

        day_handler = switch._get_mode_handler("day")
        day_handler._apply_day_mode()

        calls = fake_hass.services.async_call.call_args_list
        assert len(calls) == 1
        _, _, payload = calls[0][0]
        assert "brightness_pct" in payload
        assert "color_temp_kelvin" not in payload

    def test_both_controls_off_no_call(self, make_switch, fake_hass):
        """Both Control switches OFF → _build_day_payload returns None → no call."""
        switch, ctrl_brightness, ctrl_color = make_switch(day_mode=True)
        ctrl_brightness._attr_is_on = False
        ctrl_color._attr_is_on = False
        fake_hass.states.set("sensor.lux", FakeState(state="50"))

        day_handler = switch._get_mode_handler("day")
        day_handler._apply_day_mode()

        fake_hass.services.async_call.assert_not_called()


class TestMonitoringRecordsAppliedNotComputed:
    """Expected state and target must mirror what was sent, not what was computed.

    The damper applies brightness and colour independently, so one can be sent
    while the other is skipped. The monitoring sensors and the expected state
    used to record the freshly computed value of the skipped attribute, so the
    target drifted from what the light actually had.
    """

    def test_color_not_sent_keeps_previous_kelvin(self, make_switch, fake_hass):
        """Brightness update with a sub-threshold kelvin keeps the old kelvin."""
        switch, *_ = make_switch(
            options={"lux_smoothing_samples": 1}, day_mode=True
        )
        fake_hass.states.set("sensor.lux", FakeState(state="50"))
        switch._circadian.get_kelvin = Mock(return_value=(4000, 30.0))

        day_handler = switch._get_mode_handler("day")
        day_handler._apply_day_mode()

        # Brightness moves >= threshold (60 -> 54), kelvin moves < 50K.
        fake_hass.states.set("sensor.lux", FakeState(state="56"))
        switch._circadian.get_kelvin = Mock(return_value=(4030, 29.8))
        day_handler._apply_day_mode()

        calls = fake_hass.services.async_call.call_args_list
        payload = calls[-1][0][2]
        assert payload["brightness_pct"] == 54
        assert "color_temp_kelvin" not in payload

        expected = switch._state_ctrl.get_expected_state("light.a")
        assert expected["brightness_pct"] == 54
        assert expected["kelvin"] == 4000  # previous, not the computed 4030

        target = switch.get_last_applied_target()
        assert target.brightness_pct == 54
        assert target.kelvin == 4000

    def test_brightness_not_sent_keeps_previous_brightness(self, make_switch, fake_hass):
        """Colour update with a sub-threshold brightness re-affirms the old brightness."""
        switch, *_ = make_switch(
            options={
                "brightness_change_threshold_pct": 100,  # block brightness
                "lux_smoothing_samples": 1,
            },
            day_mode=True,
        )
        fake_hass.states.set("sensor.lux", FakeState(state="50"))
        switch._circadian.get_kelvin = Mock(return_value=(4000, 30.0))

        day_handler = switch._get_mode_handler("day")
        day_handler._apply_day_mode()

        # Colour moves >= 50K, brightness below the (huge) threshold.
        fake_hass.states.set("sensor.lux", FakeState(state="56"))
        switch._circadian.get_kelvin = Mock(return_value=(3500, 25.0))
        day_handler._apply_day_mode()

        calls = fake_hass.services.async_call.call_args_list
        payload = calls[-1][0][2]
        assert payload["brightness_pct"] == 60  # Re-affirmed, not recomputed
        assert payload["color_temp_kelvin"] == 3500

        expected = switch._state_ctrl.get_expected_state("light.a")
        assert expected["kelvin"] == 3500
        assert expected["brightness_pct"] == 60  # previous, not recomputed

        target = switch.get_last_applied_target()
        assert target.kelvin == 3500
        assert target.brightness_pct == 60
