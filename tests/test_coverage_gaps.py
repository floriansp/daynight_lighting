"""Tests closing remaining coverage gaps in switch.py — all 20 untested paths.

Medium priority (1-10): real scenarios.
Low priority (11-20): defensive guards and edge cases.

NOTE: These tests use internal APIs that have been refactored. Many test
methods that no longer exist on the switch (moved to mode handlers).
"""

from __future__ import annotations



from custom_components.daynight_lighting.const import DOMAIN

from tests.conftest import FakeState


# Skip all tests in this file - they use old internal APIs that moved to mode handlers
# Module-level skip removed - individual tests marked with @pytest.mark.skip if not yet refactored


# ===================================================================
#  MEDIUM PRIORITY — real scenarios
# ===================================================================


class TestOffTimerHeldLights:
    """#1: _off_timer_result leaves held lights alone."""

    def test_held_lights_skip_off_timer(self, make_switch, fake_hass):
        """Held lights are skipped when the off-timer fires."""
        switch, *_ = make_switch(day_mode=False)

        # Mark lights as controlled so they'd normally be turned off
        switch._state_ctrl.mark_controlled(["light.a", "light.b"])
        # A visitor holds both lights on until the phase ends
        switch._state_ctrl.set_hold(["light.a", "light.b"], reason="service")

        # Get night handler and call _off_timer_result
        night_handler = switch._get_mode_handler("night")
        lights, reason = night_handler._off_timer_result()

        assert lights == []
        assert reason == "no lights to turn off"


class TestStartListenersNoMotionSensor:
    """#3: _start_listeners with no motion sensor configured."""

    def test_no_motion_sensor(self, make_switch, fake_hass):
        """No motion sensor → motion detection returns False."""
        switch, *_ = make_switch(
            day_mode=False,
            options={"motion_sensor": None},
        )
        assert switch._motion.get_motion_sensor_entity() is None
        assert switch._motion.has_motion_now() is False


class TestStartListenersNoLightSensor:
    """#4: _start_listeners with no light sensor configured."""

    def test_no_light_sensor_day_mode_skips(self, make_switch, fake_hass):
        """No light sensor → _apply_day_mode skips (lux is None)."""
        switch, *_ = make_switch(
            day_mode=True,
            options={"light_sensor": None},
        )
        # Get day handler and call _apply_day_mode
        day_handler = switch._get_mode_handler("day")
        day_handler._apply_day_mode()
        fake_hass.services.async_call.assert_not_called()


class TestInitialNightModeMotionAlreadyOn:
    """#5: Switch starts in night mode with motion already ON."""

    def test_initial_night_motion_on_turns_lights_on(
        self, make_switch, fake_hass
    ):
        """Night mode + motion already ON at _start_listeners
        → immediate _handle_motion_on, lights turned on."""
        from datetime import datetime
        from unittest.mock import patch

        # Pre-set light states (off) and motion (on) BEFORE creating switch
        fake_hass.states.set("light.a", FakeState(state="off"))
        fake_hass.states.set("light.b", FakeState(state="off"))
        fake_hass.states.set(
            "binary_sensor.motion", FakeState(state="on")
        )

        switch, *_ = make_switch(day_mode=False)

        # Reset mock – make_switch doesn't call _start_listeners
        fake_hass.services.async_call.reset_mock()

        # Mock dt_util for schedule operations
        with patch('custom_components.daynight_lighting.schedule.dt_util') as mock_dt:
            mock_dt.now.return_value = datetime(2026, 6, 15, 23, 0, 0)
            mock_dt.as_local.return_value = datetime(2026, 6, 15, 23, 0, 0)
            # Now call _start_listeners → detects night + motion ON
            switch._start_listeners()

        # Should have called light.turn_on
        turn_on_calls = [
            c
            for c in fake_hass.services.async_call.call_args_list
            if c[0][1] == "turn_on"
        ]
        assert len(turn_on_calls) >= 1

        # Lights are marked controlled
        assert switch._state_ctrl.is_controlled_by_us("light.a")
        assert switch._state_ctrl.is_controlled_by_us("light.b")


class TestLightMatchesNightValuesException:
    """#6: _light_matches_night_values with invalid/extreme color_temp."""

    def test_invalid_color_temp_string(self, make_switch, fake_hass):
        """Non-numeric color_temp → exception caught, returns True."""
        switch, *_ = make_switch(day_mode=False)
        fake_hass.states.set(
            "light.a",
            FakeState(
                state="on",
                attributes={"brightness": 204, "color_temp": "invalid"},
            ),
        )
        # Get night handler and call _light_matches_night_values
        night_handler = switch._get_mode_handler("night")
        result = night_handler._light_matches_night_values("light.a")
        assert result is True

    def test_zero_color_temp_mired(self, make_switch, fake_hass):
        """color_temp=0 → treated as "no colour to compare" → matches (True)."""
        switch, *_ = make_switch(day_mode=False)
        fake_hass.states.set(
            "light.a",
            FakeState(
                state="on",
                attributes={"brightness": 204, "color_temp": 0},
            ),
        )
        # Get night handler and call _light_matches_night_values
        night_handler = switch._get_mode_handler("night")
        result = night_handler._light_matches_night_values("light.a")
        # 0 mired is not a usable colour temperature: the comparison falls
        # through to the RGB/HS/XY path (none present), so colour is not a
        # divergence. Brightness (204 ≈ 80%) matches → True.
        assert result is True


class TestAsyncOptionsChangedSwitchOff:
    """#7: async_options_changed when main switch is OFF → no-op."""

    def test_options_changed_switch_off_is_noop(
        self, make_switch, fake_hass
    ):
        switch, *_ = make_switch(day_mode=True)
        switch._attr_is_on = False
        fake_hass.services.async_call.reset_mock()

        switch.async_options_changed()

        fake_hass.services.async_call.assert_not_called()


class TestHandleMotionOnAllLightsControlled:
    """#8: _handle_motion_on all lights already controlled and matching → no-op."""

    def test_all_lights_on_controlled_and_matching_skips_turn_on(
        self, make_switch, fake_hass
    ):
        switch, *_ = make_switch(day_mode=False)

        # Both lights ON, controlled by us, and exactly matching night values:
        # brightness 204 ≈ 80%, color_temp 225 mired ≈ 4450K (elevation 30).
        fake_hass.states.set(
            "light.a",
            FakeState(state="on", attributes={"brightness": 204, "color_temp": 225}),
        )
        fake_hass.states.set(
            "light.b",
            FakeState(state="on", attributes={"brightness": 204, "color_temp": 225}),
        )
        switch._state_ctrl.mark_controlled(["light.a", "light.b"])

        fake_hass.services.async_call.reset_mock()
        switch._handle_motion_on()

        # No re-apply: the identical values are already in place.
        turn_on_calls = [
            c
            for c in fake_hass.services.async_call.call_args_list
            if c[0][1] == "turn_on"
        ]
        assert turn_on_calls == []

    def test_controlled_light_with_drifted_colour_still_reapplies(
        self, make_switch, fake_hass
    ):
        """A controlled light whose colour drifted (circadian moved) re-applies."""
        switch, *_ = make_switch(day_mode=False)

        # brightness 204 ≈ 80%, but colour_temp is far off the expected
        # ~225 mired (4450K at elevation 30) → skip test fails → re-apply.
        fake_hass.states.set(
            "light.a",
            FakeState(
                state="on",
                attributes={"brightness": 204, "color_temp": 370},
            ),
        )
        switch._state_ctrl.mark_controlled(["light.a"])

        fake_hass.services.async_call.reset_mock()
        switch._handle_motion_on()

        turn_on_calls = [
            c
            for c in fake_hass.services.async_call.call_args_list
            if c[0][1] == "turn_on"
        ]
        assert len(turn_on_calls) >= 1

    def test_small_circadian_drift_still_reapplies(
        self, make_switch, fake_hass
    ):
        """Even a small colour drift (circadian creep) triggers a re-apply.

        The skip must be tight: unlike the loose adoption tolerance, a
        controlled light follows the circadian curve step by step, not only
        after a large jump.
        """
        switch, *_ = make_switch(day_mode=False)

        # 225 → 240 mired is only 15 mired off (well inside the old 75-mired
        # adoption tolerance) but clearly not the exact target → re-apply.
        fake_hass.states.set(
            "light.a",
            FakeState(
                state="on",
                attributes={"brightness": 204, "color_temp": 240},
            ),
        )
        switch._state_ctrl.mark_controlled(["light.a"])

        fake_hass.services.async_call.reset_mock()
        switch._handle_motion_on()

        turn_on_calls = [
            c
            for c in fake_hass.services.async_call.call_args_list
            if c[0][1] == "turn_on"
        ]
        assert len(turn_on_calls) >= 1


class TestBuildNightPayloadCircadianDisabled:
    """#9: _build_night_payload with circadian disabled."""

    def test_circadian_disabled_no_color(self, make_switch, fake_hass):
        switch, *_ = make_switch(
            day_mode=False,
            options={"circadian_enabled": False},
        )
        # Get night handler and call build_light_payload
        night_handler = switch._get_mode_handler("night")
        payload = night_handler.build_light_payload(["light.a"])
        assert "color_temp_kelvin" not in payload
        assert "brightness_pct" in payload
        assert payload["entity_id"] == ["light.a"]


class TestGetDesiredTurnOnParams:
    """#10: get_desired_turn_on_params edge cases."""

    def test_day_mode_lux_unavailable_brightness_zero(
        self, make_switch, fake_hass
    ):
        """Day mode, LUX unavailable → brightness_pct=0."""
        switch, *_ = make_switch(day_mode=True)
        # No LUX sensor state → get_lux → None → pct → None → 0
        result = switch.get_desired_turn_on_params()
        assert result.get("brightness_pct") == 0

    def test_circadian_disabled_no_color(self, make_switch, fake_hass):
        """Circadian disabled → no color_temp_kelvin."""
        switch, *_ = make_switch(
            day_mode=True,
            options={"circadian_enabled": False},
        )
        fake_hass.states.set("sensor.lux", FakeState(state="50"))
        result = switch.get_desired_turn_on_params()
        assert "color_temp_kelvin" not in result

    def test_night_mode_returns_night_brightness(
        self, make_switch, fake_hass
    ):
        """Night mode → returns configured night brightness."""
        switch, *_ = make_switch(
            day_mode=False,
            options={"night_brightness": 42},
        )
        result = switch.get_desired_turn_on_params()
        assert result.get("brightness_pct") == 42


# ===================================================================
#  LOW PRIORITY — defensive guards and edge cases
# ===================================================================


class TestTickDayModeEmptyLights:
    """#13: _tick_day_mode with empty lights list."""

    def test_empty_lights_no_service_calls(self, make_switch, fake_hass):
        switch, *_ = make_switch(
            day_mode=True, options={"lights": []}
        )
        # Get day handler and call tick
        day_handler = switch._get_mode_handler("day")
        day_handler.tick()
        fake_hass.services.async_call.assert_not_called()


class TestControlSwitchMissing:
    """#14-15: _is_control_brightness/color_on when switch is absent."""

    def test_brightness_switch_missing_defaults_true(
        self, make_switch, fake_hass
    ):
        switch, *_ = make_switch(day_mode=True)
        entry_data = fake_hass.data[DOMAIN][switch._config_entry.entry_id]
        entry_data.pop("control_brightness_switch", None)
        assert switch._is_control_brightness_on() is True

    def test_color_switch_missing_defaults_true(
        self, make_switch, fake_hass
    ):
        switch, *_ = make_switch(day_mode=True)
        entry_data = fake_hass.data[DOMAIN][switch._config_entry.entry_id]
        entry_data.pop("control_color_switch", None)
        assert switch._is_control_color_on() is True


class TestExtraStateAttributes:
    """#17: extra_state_attributes property."""

    def test_returns_lights_list(self, make_switch, fake_hass):
        switch, *_ = make_switch(day_mode=True)
        attrs = switch.extra_state_attributes
        assert attrs == {"lights": ["light.a", "light.b"]}

    def test_empty_lights(self, make_switch, fake_hass):
        switch, *_ = make_switch(
            day_mode=True, options={"lights": []}
        )
        attrs = switch.extra_state_attributes
        assert attrs == {"lights": []}


class TestLightMatchesNightValuesStateEdges:
    """#18: _light_matches_night_values with None or off state."""

    def test_state_none_returns_true(self, make_switch, fake_hass):
        """Missing entity → can't verify, assume OK (True)."""
        switch, *_ = make_switch(day_mode=False)
        # Get night handler and call _light_matches_night_values
        night_handler = switch._get_mode_handler("night")
        result = night_handler._light_matches_night_values("light.nonexistent")
        assert result is True

    def test_state_off_returns_true(self, make_switch, fake_hass):
        """Light is off → can't verify, assume OK (True)."""
        switch, *_ = make_switch(day_mode=False)
        fake_hass.states.set("light.a", FakeState(state="off"))
        # Get night handler and call _light_matches_night_values
        night_handler = switch._get_mode_handler("night")
        result = night_handler._light_matches_night_values("light.a")
        assert result is True

    def test_brightness_mismatch_returns_false(self, make_switch, fake_hass):
        """Brightness way off from expected → False."""
        switch, *_ = make_switch(
            day_mode=False, options={"night_brightness": 80}
        )
        # 80% expected → ~204 raw.  Set brightness=50 (~20%) → diff>10%
        fake_hass.states.set(
            "light.a",
            FakeState(
                state="on", attributes={"brightness": 50}
            ),
        )
        # Get night handler and call _light_matches_night_values
        night_handler = switch._get_mode_handler("night")
        result = night_handler._light_matches_night_values("light.a")
        assert result is False


class TestHandleMotionOnEmptyLights:
    """#19: _handle_motion_on when lights list is empty."""

    def test_no_lights_no_crash(self, make_switch, fake_hass):
        switch, *_ = make_switch(
            day_mode=False, options={"lights": []}
        )
        switch._handle_motion_on()
        fake_hass.services.async_call.assert_not_called()


class TestOffTimerHeldLightsPartial:
    """#20: _off_timer_result when only some lights are held."""

    def test_held_light_skips_turn_off(self, make_switch, fake_hass):
        """Only the non-held controlled lights are turned off."""
        switch, *_ = make_switch(day_mode=False)
        fake_hass.states.set(
            "binary_sensor.motion", FakeState(state="off")
        )

        switch._state_ctrl.mark_controlled(["light.a", "light.b"])
        switch._state_ctrl.set_hold(["light.a"], reason="service")

        # Get night handler and call _off_timer_result
        night_handler = switch._get_mode_handler("night")
        lights, reason = night_handler._off_timer_result()

        assert lights == ["light.b"]
        assert reason is None
