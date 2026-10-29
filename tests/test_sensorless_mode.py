"""Test sensorless mode fallback behaviour."""

from unittest.mock import Mock



def _day_handler_tick(switch):
    """Helper to call day mode handler tick."""
    return switch._get_mode_handler("day").tick()


def _night_handler_tick(switch):
    """Helper to call night mode handler tick."""
    return switch._get_mode_handler("night").tick()


# ======================================================================
#  Day mode fallback tests
# ======================================================================


class TestDayModeFallbackSkip:
    """Test day mode fallback=skip (default)."""

    def test_skip_does_nothing_no_lux_sensor(self, make_switch, fake_hass):
        """Skip should do nothing when no LUX sensor configured."""
        switch, *_ = make_switch(
            options={"light_sensor": None, "day_mode_fallback": "skip"}
        )

        _day_handler_tick(switch)

        fake_hass.services.async_call.assert_not_called()

    def test_skip_is_default(self, make_switch, fake_hass):
        """Skip should be default when no fallback configured."""
        switch, *_ = make_switch(options={"light_sensor": None})

        _day_handler_tick(switch)

        fake_hass.services.async_call.assert_not_called()


class TestDayModeFallbackOff:
    """Test day mode fallback=off."""

    def test_off_turns_lights_off(self, make_switch, fake_hass):
        """Off should turn lights off during day."""
        switch, *_ = make_switch(
            options={"light_sensor": None, "day_mode_fallback": "off"}
        )

        _day_handler_tick(switch)

        calls = fake_hass.services.async_call.call_args_list
        assert len(calls) == 1
        domain, service, data = calls[0][0]
        assert domain == "light"
        assert service == "turn_off"
        assert data["entity_id"] == ["light.a", "light.b"]

    def test_off_unmarks_controlled(self, make_switch, fake_hass):
        """Off should unmark lights as controlled."""
        switch, *_ = make_switch(
            options={"light_sensor": None, "day_mode_fallback": "off"}
        )

        # Mark as controlled first
        switch._state_ctrl.mark_controlled(["light.a"])
        assert switch._state_ctrl.is_controlled_by_us("light.a")

        _day_handler_tick(switch)

        # Should be unmarked
        assert not switch._state_ctrl.is_controlled_by_us("light.a")


class TestDayModeFallbackCircadianOnly:
    """Test day mode fallback=circadian_only."""

    def test_circadian_only_sets_color_temp(self, make_switch, fake_hass):
        """Circadian only should set color temperature without brightness."""
        switch, *_ = make_switch(
            options={
                "light_sensor": None,
                "day_mode_fallback": "circadian_only",
                "circadian_enabled": True,
            }
        )

        # Mock circadian to return specific kelvin
        switch._circadian.get_kelvin = Mock(return_value=(3500, 30.0))

        _day_handler_tick(switch)

        calls = fake_hass.services.async_call.call_args_list
        assert len(calls) == 1
        _, _, payload = calls[0][0]
        assert payload["entity_id"] == ["light.a", "light.b"]
        assert payload["color_temp_kelvin"] == 3500
        assert "brightness_pct" not in payload

    def test_circadian_only_disabled_does_nothing(self, make_switch, fake_hass):
        """Circadian only should do nothing when circadian disabled."""
        switch, *_ = make_switch(
            options={
                "light_sensor": None,
                "day_mode_fallback": "circadian_only",
                "circadian_enabled": False,
            }
        )

        _day_handler_tick(switch)

        fake_hass.services.async_call.assert_not_called()

    def test_circadian_only_marks_controlled(self, make_switch, fake_hass):
        """Circadian only should mark lights as controlled."""
        switch, *_ = make_switch(
            options={
                "light_sensor": None,
                "day_mode_fallback": "circadian_only",
                "circadian_enabled": True,
            }
        )
        switch._circadian.get_kelvin = Mock(return_value=(3500, 30.0))

        _day_handler_tick(switch)

        assert switch._state_ctrl.is_controlled_by_us("light.a")


class TestDayModeFallbackFixed:
    """Test day mode fallback=fixed."""

    def test_fixed_uses_configured_brightness(self, make_switch, fake_hass):
        """Fixed should use configured fixed brightness."""
        switch, *_ = make_switch(
            options={
                "light_sensor": None,
                "day_mode_fallback": "fixed",
                "day_fixed_brightness_pct": 75,
                "circadian_enabled": False,
            }
        )

        _day_handler_tick(switch)

        calls = fake_hass.services.async_call.call_args_list
        assert len(calls) == 1
        _, _, payload = calls[0][0]
        assert payload["entity_id"] == ["light.a", "light.b"]
        assert payload["brightness_pct"] == 75
        assert "color_temp_kelvin" not in payload

    def test_fixed_with_circadian(self, make_switch, fake_hass):
        """Fixed should include circadian color when enabled."""
        switch, *_ = make_switch(
            options={
                "light_sensor": None,
                "day_mode_fallback": "fixed",
                "day_fixed_brightness_pct": 60,
                "circadian_enabled": True,
            }
        )
        switch._circadian.get_kelvin = Mock(return_value=(4200, 45.0))

        _day_handler_tick(switch)

        calls = fake_hass.services.async_call.call_args_list
        assert len(calls) == 1
        _, _, payload = calls[0][0]
        assert payload["brightness_pct"] == 60
        assert payload["color_temp_kelvin"] == 4200

    def test_fixed_uses_default_80_pct(self, make_switch, fake_hass):
        """Fixed should default to 80% brightness."""
        switch, *_ = make_switch(
            options={
                "light_sensor": None,
                "day_mode_fallback": "fixed",
                "circadian_enabled": False,
            }
        )

        _day_handler_tick(switch)

        calls = fake_hass.services.async_call.call_args_list
        _, _, payload = calls[0][0]
        assert payload["brightness_pct"] == 80

    def test_fixed_marks_controlled(self, make_switch, fake_hass):
        """Fixed should mark lights as controlled."""
        switch, *_ = make_switch(
            options={
                "light_sensor": None,
                "day_mode_fallback": "fixed",
                "day_fixed_brightness_pct": 50,
            }
        )

        _day_handler_tick(switch)

        assert switch._state_ctrl.is_controlled_by_us("light.a")


# ======================================================================
#  Night mode fallback tests
# ======================================================================


class TestNightModeFallbackSkip:
    """Test night mode fallback=skip (default)."""

    def test_skip_does_nothing_no_motion_sensor(self, make_switch, fake_hass):
        """Skip should do nothing when no motion sensor configured."""
        switch, *_ = make_switch(
            options={"motion_sensor": None, "night_mode_fallback": "skip"},
            day_mode=False,
        )

        _night_handler_tick(switch)

        fake_hass.services.async_call.assert_not_called()

    def test_skip_is_default(self, make_switch, fake_hass):
        """Skip should be default when no fallback configured."""
        switch, *_ = make_switch(
            options={"motion_sensor": None}, day_mode=False
        )

        _night_handler_tick(switch)

        fake_hass.services.async_call.assert_not_called()


class TestNightModeFallbackKeep:
    """Test night mode fallback=keep."""

    def test_keep_does_nothing(self, make_switch, fake_hass):
        """Keep should do nothing (keep current state)."""
        switch, *_ = make_switch(
            options={"motion_sensor": None, "night_mode_fallback": "keep"},
            day_mode=False,
        )

        _night_handler_tick(switch)

        fake_hass.services.async_call.assert_not_called()


class TestNightModeFallbackOff:
    """Test night mode fallback=off."""

    def test_off_turns_lights_off(self, make_switch, fake_hass):
        """Off should turn lights off during night."""
        switch, *_ = make_switch(
            options={"motion_sensor": None, "night_mode_fallback": "off"},
            day_mode=False,
        )

        _night_handler_tick(switch)

        calls = fake_hass.services.async_call.call_args_list
        assert len(calls) == 1
        domain, service, data = calls[0][0]
        assert domain == "light"
        assert service == "turn_off"
        assert data["entity_id"] == ["light.a", "light.b"]

    def test_off_unmarks_controlled(self, make_switch, fake_hass):
        """Off should unmark lights as controlled."""
        switch, *_ = make_switch(
            options={"motion_sensor": None, "night_mode_fallback": "off"},
            day_mode=False,
        )

        # Mark as controlled first
        switch._state_ctrl.mark_controlled(["light.a"])
        assert switch._state_ctrl.is_controlled_by_us("light.a")

        _night_handler_tick(switch)

        # Should be unmarked
        assert not switch._state_ctrl.is_controlled_by_us("light.a")


class TestNightModeFallbackOn:
    """Test night mode fallback=on."""

    def test_on_uses_night_brightness(self, make_switch, fake_hass):
        """On should use configured night brightness."""
        switch, *_ = make_switch(
            options={
                "motion_sensor": None,
                "night_mode_fallback": "on",
                "night_brightness": 40,
                "circadian_enabled": False,
            },
            day_mode=False,
        )

        _night_handler_tick(switch)

        calls = fake_hass.services.async_call.call_args_list
        assert len(calls) == 1
        _, _, payload = calls[0][0]
        assert payload["entity_id"] == ["light.a", "light.b"]
        assert payload["brightness_pct"] == 40
        assert "color_temp_kelvin" not in payload

    def test_on_with_circadian(self, make_switch, fake_hass):
        """On should include circadian color when enabled."""
        switch, *_ = make_switch(
            options={
                "motion_sensor": None,
                "night_mode_fallback": "on",
                "night_brightness": 30,
                "circadian_enabled": True,
            },
            day_mode=False,
        )
        switch._circadian.get_kelvin = Mock(return_value=(2800, -20.0))

        _night_handler_tick(switch)

        calls = fake_hass.services.async_call.call_args_list
        assert len(calls) == 1
        _, _, payload = calls[0][0]
        assert payload["brightness_pct"] == 30
        assert payload["color_temp_kelvin"] == 2800

    def test_on_uses_default_80_pct(self, make_switch, fake_hass):
        """On should use default night brightness (80)."""
        switch, *_ = make_switch(
            options={
                "motion_sensor": None,
                "night_mode_fallback": "on",
                "circadian_enabled": False,
            },
            day_mode=False,
        )

        _night_handler_tick(switch)

        calls = fake_hass.services.async_call.call_args_list
        _, _, payload = calls[0][0]
        assert payload["brightness_pct"] == 80

    def test_on_marks_controlled(self, make_switch, fake_hass):
        """On should mark lights as controlled."""
        switch, *_ = make_switch(
            options={
                "motion_sensor": None,
                "night_mode_fallback": "on",
                "night_brightness": 50,
            },
            day_mode=False,
        )

        _night_handler_tick(switch)

        assert switch._state_ctrl.is_controlled_by_us("light.a")


# ======================================================================
#  Control switch interaction tests
# ======================================================================


class TestControlSwitchInteraction:
    """Test interaction with Control Brightness/Color switches."""

    def test_day_fixed_respects_control_brightness_off(self, make_switch, fake_hass):
        """Fixed mode should not set brightness when Control Brightness is OFF."""
        switch, ctrl_brightness, _ = make_switch(
            options={
                "light_sensor": None,
                "day_mode_fallback": "fixed",
                "day_fixed_brightness_pct": 70,
                "circadian_enabled": False,
            }
        )
        # Turn Control Brightness OFF
        ctrl_brightness._attr_is_on = False

        _day_handler_tick(switch)

        # Should not call turn_on (no brightness or color to set)
        fake_hass.services.async_call.assert_not_called()

    def test_day_circadian_only_respects_control_color_off(self, make_switch, fake_hass):
        """Circadian only mode should do nothing when Control Color is OFF."""
        switch, _, ctrl_color = make_switch(
            options={
                "light_sensor": None,
                "day_mode_fallback": "circadian_only",
                "circadian_enabled": True,
            }
        )
        switch._circadian.get_kelvin = Mock(return_value=(3500, 30.0))
        # Turn Control Color OFF
        ctrl_color._attr_is_on = False

        _day_handler_tick(switch)

        fake_hass.services.async_call.assert_not_called()

    def test_night_on_respects_control_brightness_off(self, make_switch, fake_hass):
        """Night on mode should not set brightness when Control Brightness is OFF."""
        switch, ctrl_brightness, _ = make_switch(
            options={
                "motion_sensor": None,
                "night_mode_fallback": "on",
                "night_brightness": 50,
                "circadian_enabled": True,
            },
            day_mode=False,
        )
        switch._circadian.get_kelvin = Mock(return_value=(2800, -20.0))
        # Turn Control Brightness OFF
        ctrl_brightness._attr_is_on = False

        _night_handler_tick(switch)

        # Should only set color, not brightness
        calls = fake_hass.services.async_call.call_args_list
        assert len(calls) == 1
        _, _, payload = calls[0][0]
        assert "brightness_pct" not in payload
        assert payload["color_temp_kelvin"] == 2800
