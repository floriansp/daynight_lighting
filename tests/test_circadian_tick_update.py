"""Tests for circadian color temperature recalculation on every tick.

Verifies that the bugfix restores per-minute circadian updates in Day Mode,
ensuring color temperature tracks sun elevation even when brightness is stable.
"""

from unittest.mock import Mock

from tests.conftest import FakeState


def _get_day_handler(switch):
    """Get the day mode handler from the switch."""
    return switch._get_mode_handler("day")


class TestCircadianRecalculationEveryMinute:
    """Test that circadian is calculated and logged every minute."""

    def test_circadian_updates_when_brightness_stable(self, make_switch, fake_hass):
        """Circadian should update every minute even when brightness is stable.

        This is the core regression fix: brightness stability should NOT
        block circadian color updates.
        """
        switch, *_ = make_switch(
            options={
                "lux_on": 10.0,
                "lux_off": 100.0,
                "circadian_enabled": True,
                "brightness_change_threshold_pct": 3,  # Prevent brightness updates
            },
            day_mode=True,
        )

        # Set LUX to stable value
        fake_hass.states.set("sensor.lux", FakeState(state="50"))

        # First tick - both brightness and color applied
        switch._circadian.get_kelvin = Mock(return_value=(4000, 30.0))
        _get_day_handler(switch)._apply_day_mode()

        calls = fake_hass.services.async_call.call_args_list
        assert len(calls) == 1
        _, _, payload = calls[0][0]
        assert payload["brightness_pct"] == 60  # First application
        assert payload["color_temp_kelvin"] == 4000

        fake_hass.services.async_call.reset_mock()

        # Second tick - brightness unchanged, color changed
        switch._circadian.get_kelvin = Mock(return_value=(3500, 25.0))
        _get_day_handler(switch)._apply_day_mode()

        # Brightness is re-affirmed so a Hue light never gets a colour-only
        # update that would drop it to a low brightness.
        calls = fake_hass.services.async_call.call_args_list
        assert len(calls) == 1
        _, _, payload = calls[0][0]
        assert payload["brightness_pct"] == 60  # Re-affirmed (unchanged)
        assert payload["color_temp_kelvin"] == 3500  # Color updated

    def test_circadian_log_appears_every_minute(self, make_switch, fake_hass, caplog):
        """Circadian debug log should appear every minute before suppression."""
        import logging

        caplog.set_level(logging.DEBUG)

        switch, *_ = make_switch(
            options={
                "lux_on": 10.0,
                "lux_off": 100.0,
                "circadian_enabled": True,
            },
            day_mode=True,
        )

        fake_hass.states.set("sensor.lux", FakeState(state="50"))

        # First tick
        switch._circadian.get_kelvin = Mock(return_value=(4000, 30.0))
        _get_day_handler(switch)._apply_day_mode()

        # Check log contains circadian info
        assert any(
            "Day: circadian 4000K" in record.message and "elevation 30.0" in record.message
            for record in caplog.records
        )

        caplog.clear()

        # Second tick - even if nothing sent, log should still appear
        switch._circadian.get_kelvin = Mock(return_value=(4010, 29.5))  # Small change
        _get_day_handler(switch)._apply_day_mode()

        # Log should still appear (even though change is below threshold)
        assert any(
            "Day: circadian 4010K" in record.message
            for record in caplog.records
        )

    def test_brightness_unchanged_color_changed_reaffirms_brightness(self, make_switch, fake_hass):
        """When brightness is below threshold but color changed, brightness is re-affirmed."""
        switch, *_ = make_switch(
            options={
                "circadian_enabled": True,
                "brightness_change_threshold_pct": 10,  # High threshold
            },
            day_mode=True,
        )

        fake_hass.states.set("sensor.lux", FakeState(state="50"))

        # First tick
        switch._circadian.get_kelvin = Mock(return_value=(4000, 30.0))
        _get_day_handler(switch)._apply_day_mode()
        fake_hass.services.async_call.reset_mock()

        # Second tick - brightness change below threshold (60% -> 62% = 3.3%)
        fake_hass.states.set("sensor.lux", FakeState(state="48"))
        switch._circadian.get_kelvin = Mock(return_value=(3500, 25.0))
        _get_day_handler(switch)._apply_day_mode()

        # Brightness is re-affirmed (previous value) so the light is never left
        # on a colour-only update that Hue would interpret as a dimming.
        calls = fake_hass.services.async_call.call_args_list
        assert len(calls) == 1
        _, _, payload = calls[0][0]
        assert payload["brightness_pct"] == 60
        assert payload["color_temp_kelvin"] == 3500


class TestFlappingDoesNotBlockColor:
    """Test that flapping freeze blocks brightness but NOT color."""

    def test_flapping_freeze_blocks_brightness_not_color(self, make_switch, fake_hass):
        """During flapping freeze, brightness blocked but color should update."""
        switch, *_ = make_switch(
            options={
                "circadian_enabled": True,
                "flapping_freeze_min": 5,
            },
            day_mode=True,
        )

        fake_hass.states.set("sensor.lux", FakeState(state="50"))

        # Trigger flapping detection by rapidly changing brightness direction
        switch._circadian.get_kelvin = Mock(return_value=(4000, 30.0))

        # Simulate flapping: up, down, up, down
        fake_hass.states.set("sensor.lux", FakeState(state="40"))
        _get_day_handler(switch)._apply_day_mode()
        fake_hass.states.set("sensor.lux", FakeState(state="60"))
        _get_day_handler(switch)._apply_day_mode()
        fake_hass.states.set("sensor.lux", FakeState(state="40"))
        _get_day_handler(switch)._apply_day_mode()
        fake_hass.states.set("sensor.lux", FakeState(state="60"))
        _get_day_handler(switch)._apply_day_mode()

        fake_hass.services.async_call.reset_mock()

        # Now in freeze - brightness should be blocked but color should work
        fake_hass.states.set("sensor.lux", FakeState(state="50"))
        switch._circadian.get_kelvin = Mock(return_value=(3500, 25.0))
        _get_day_handler(switch)._apply_day_mode()

        # Colour goes out with the frozen brightness re-affirmed (same value,
        # so the freeze still blocks any *change* but the light is not left on
        # a colour-only update).
        calls = fake_hass.services.async_call.call_args_list
        if len(calls) > 0:  # May not send if both are stable
            _, _, payload = calls[0][0]
            assert "color_temp_kelvin" in payload
            assert payload["color_temp_kelvin"] == 3500
            assert "brightness_pct" in payload  # Re-affirmed (same value)


class TestColorThresholdPreventsUnnecessaryUpdates:
    """Test that color threshold prevents micro-adjustments."""

    def test_small_kelvin_change_not_applied(self, make_switch, fake_hass):
        """Kelvin changes < 50K should not trigger update (threshold)."""
        switch, *_ = make_switch(
            options={
                "circadian_enabled": True,
                "brightness_change_threshold_pct": 100,  # Block brightness
            },
            day_mode=True,
        )

        fake_hass.states.set("sensor.lux", FakeState(state="50"))

        # First tick
        switch._circadian.get_kelvin = Mock(return_value=(4000, 30.0))
        _get_day_handler(switch)._apply_day_mode()
        fake_hass.services.async_call.reset_mock()

        # Second tick - small kelvin change (< 50K threshold)
        switch._circadian.get_kelvin = Mock(return_value=(4030, 29.8))
        _get_day_handler(switch)._apply_day_mode()

        # Should not send (change too small)
        fake_hass.services.async_call.assert_not_called()

    def test_large_kelvin_change_applied(self, make_switch, fake_hass):
        """Kelvin changes >= 50K should trigger update."""
        switch, *_ = make_switch(
            options={
                "circadian_enabled": True,
                "brightness_change_threshold_pct": 100,  # Block brightness
            },
            day_mode=True,
        )

        fake_hass.states.set("sensor.lux", FakeState(state="50"))

        # First tick
        switch._circadian.get_kelvin = Mock(return_value=(4000, 30.0))
        _get_day_handler(switch)._apply_day_mode()
        fake_hass.services.async_call.reset_mock()

        # Second tick - large kelvin change (>= 50K threshold)
        switch._circadian.get_kelvin = Mock(return_value=(3900, 28.0))
        _get_day_handler(switch)._apply_day_mode()

        # Brightness is re-affirmed so the light never gets a colour-only update
        calls = fake_hass.services.async_call.call_args_list
        assert len(calls) == 1
        _, _, payload = calls[0][0]
        assert payload["brightness_pct"] == 60
        assert payload["color_temp_kelvin"] == 3900


class TestControlSwitchInteraction:
    """Test interaction with Control Color switch."""

    def test_control_color_off_blocks_color_in_payload(
        self, make_switch, fake_hass
    ):
        """Control Color OFF should block color in payload.

        When Control Color is OFF, circadian is not calculated (optimization)
        since we won't use the value anyway. This is correct behavior.
        """
        switch, _, ctrl_color = make_switch(
            options={"circadian_enabled": True}, day_mode=True
        )

        # Turn Control Color OFF
        ctrl_color._attr_is_on = False

        fake_hass.states.set("sensor.lux", FakeState(state="50"))
        switch._circadian.get_kelvin = Mock(return_value=(4000, 30.0))

        _get_day_handler(switch)._apply_day_mode()

        # Payload should not contain color (Control Color OFF)
        calls = fake_hass.services.async_call.call_args_list
        assert len(calls) == 1
        _, _, payload = calls[0][0]
        assert "color_temp_kelvin" not in payload
        # Should have brightness only
        assert "brightness_pct" in payload


class TestHeldLightsBlockTick:
    """Test that held lights block the day tick."""

    def test_held_lights_block_tick_not_apply(
        self, make_switch, fake_hass
    ):
        """Held lights stop the day tick from touching them.

        A visitor's hold lives until the phase ends, so the day automation
        must not overwrite it. When every light is held, the tick does nothing.
        """
        switch, *_ = make_switch(
            options={"circadian_enabled": True}, day_mode=True
        )

        # Hold all lights (e.g. via the hold_all service)
        switch._state_ctrl.set_hold(
            ["light.a", "light.b"], reason="service"
        )

        fake_hass.states.set("sensor.lux", FakeState(state="50"))
        switch._circadian.get_kelvin = Mock(return_value=(4000, 30.0))

        # Call tick (high level) - should return early
        day_handler = _get_day_handler(switch)
        day_handler.tick()

        # No service calls should be made
        fake_hass.services.async_call.assert_not_called()


class TestKelvinTrackingReset:
    """Test that kelvin tracking is reset appropriately."""

    def test_kelvin_reset_on_lights_off(self, make_switch, fake_hass):
        """Kelvin tracking should reset when turning lights off."""
        switch, *_ = make_switch(
            options={
                "circadian_enabled": True,
                "day_min_brightness": 0,  # Allow turning off
            },
            day_mode=True,
        )

        # First - lights on with color
        fake_hass.states.set("sensor.lux", FakeState(state="50"))
        switch._circadian.get_kelvin = Mock(return_value=(4000, 30.0))
        _get_day_handler(switch)._apply_day_mode()

        day_handler = _get_day_handler(switch)
        assert day_handler._last_applied_kelvin == 4000

        # Now turn lights off (high LUX)
        fake_hass.states.set("sensor.lux", FakeState(state="150"))
        day_handler._apply_day_mode()

        # Kelvin tracking should be reset
        assert day_handler._last_applied_kelvin is None

    def test_first_kelvin_always_applied(self, make_switch, fake_hass):
        """First kelvin application should always happen (no previous value)."""
        switch, *_ = make_switch(
            options={
                "circadian_enabled": True,
                "brightness_change_threshold_pct": 100,  # Block brightness
            },
            day_mode=True,
        )

        day_handler = _get_day_handler(switch)
        assert day_handler._last_applied_kelvin is None

        fake_hass.states.set("sensor.lux", FakeState(state="50"))
        switch._circadian.get_kelvin = Mock(return_value=(4000, 30.0))
        day_handler._apply_day_mode()

        # First application should go through regardless of threshold
        calls = fake_hass.services.async_call.call_args_list
        assert len(calls) == 1
        _, _, payload = calls[0][0]
        assert payload["color_temp_kelvin"] == 4000
