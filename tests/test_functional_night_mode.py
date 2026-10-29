"""Functional tests: Night-mode orchestration in DayNightLightingSwitch."""

from __future__ import annotations


from custom_components.daynight_lighting.const import MODE_DAY, MODE_NIGHT

from tests.conftest import FakeState


class TestHandleMotionOn:
    """Tests for _handle_motion_on (motion detected → turn on lights)."""

    def test_lights_off_turns_on_with_night_payload(
        self, make_switch, fake_hass
    ):
        """Lights off → turn on with night brightness + circadian color."""
        switch, *_ = make_switch(day_mode=False)
        # Lights are off (default — no state set means state is None)

        switch._handle_motion_on()

        calls = fake_hass.services.async_call.call_args_list
        assert len(calls) == 1
        domain, service, payload = calls[0][0]
        assert domain == "light"
        assert service == "turn_on"
        assert set(payload["entity_id"]) == {"light.a", "light.b"}
        assert payload["brightness_pct"] == 80
        assert "color_temp_kelvin" in payload

    def test_lights_off_marks_controlled(self, make_switch, fake_hass):
        """After motion ON, lights are marked as controlled."""
        switch, *_ = make_switch(day_mode=False)

        switch._handle_motion_on()

        assert switch._state_ctrl.is_controlled_by_us("light.a")
        assert switch._state_ctrl.is_controlled_by_us("light.b")

    def test_already_on_matching_values_takes_control(
        self, make_switch, fake_hass
    ):
        """Light on with matching brightness/color → take control."""
        switch, *_ = make_switch(day_mode=False)

        # Set light.a ON with values matching night settings
        # night_brightness=80 → 80% of 255 ≈ 204
        # circadian kelvin for elevation=30 → 4450K → mired=round(1e6/4450)=225
        fake_hass.states.set(
            "light.a",
            FakeState(
                state="on",
                attributes={"brightness": 204, "color_temp": 225},
            ),
        )

        switch._handle_motion_on()

        assert switch._state_ctrl.is_controlled_by_us("light.a")
        assert switch._state_ctrl.is_controlled_by_us("light.b")

    def test_held_light_is_left_alone(self, make_switch, fake_hass):
        """A held light is not switched by motion on: it belongs to a visitor."""
        switch, *_ = make_switch(day_mode=False)
        switch._state_ctrl.set_hold(["light.a"], reason="service")

        switch._handle_motion_on()

        calls = fake_hass.services.async_call.call_args_list
        assert len(calls) == 1
        payload = calls[0][0][2]
        assert payload["entity_id"] == ["light.b"]

    def test_xy_bulb_at_correct_white_not_reapplied(
        self, make_switch, fake_hass
    ):
        """A Hue (xy) bulb already at our circadian white is not re-applied.

        Hue bulbs report ``xy_color``/``color_mode: "xy"`` instead of a mired
        ``color_temp``. Without colourimetric comparison every motion event
        re-applies an unchanged white and permanently re-arms the grace
        period, which is what let a scene slip through undetected.
        """
        from custom_components.daynight_lighting.domain.colorimetry import kelvin_to_xy

        switch, *_ = make_switch(day_mode=False)
        switch._state_ctrl.mark_controlled(["light.a", "light.b"])

        fake_hass.states.set(
            "light.a",
            FakeState(
                state="on",
                attributes={
                    "brightness": 204,  # 80% of 255
                    "color_mode": "xy",
                    "xy_color": list(kelvin_to_xy(4450)),
                },
            ),
        )
        fake_hass.states.set("light.b", FakeState(state="off"))

        switch._handle_motion_on()

        calls = fake_hass.services.async_call.call_args_list
        assert len(calls) == 1
        payload = calls[0][0][2]
        assert set(payload["entity_id"]) == {"light.b"}

    def test_scene_diverged_brightness_held(self, make_switch, fake_hass):
        """A controlled light with a scene's brightness is held (detected)."""
        from custom_components.daynight_lighting.domain.colorimetry import kelvin_to_xy

        switch, *_ = make_switch(day_mode=False)
        switch._state_ctrl.mark_controlled(["light.a"])

        # Scene: correct colour, but 36% instead of the 80% night target.
        fake_hass.states.set(
            "light.a",
            FakeState(
                state="on",
                attributes={
                    "brightness": 92,  # 36% of 255
                    "color_mode": "xy",
                    "xy_color": list(kelvin_to_xy(4450)),
                },
            ),
        )
        fake_hass.states.set("light.b", FakeState(state="off"))

        switch._handle_motion_on()

        calls = fake_hass.services.async_call.call_args_list
        assert len(calls) == 1
        payload = calls[0][0][2]
        assert "light.a" not in payload["entity_id"]
        assert switch._state_ctrl.is_held("light.a")
        assert switch._state_ctrl.get_hold_reason("light.a") == "detected"

    def test_scene_diverged_color_held(self, make_switch, fake_hass):
        """A scene keeping brightness but changing colour is held (detected)."""
        from custom_components.daynight_lighting.domain.colorimetry import kelvin_to_xy

        switch, *_ = make_switch(day_mode=False)
        switch._state_ctrl.mark_controlled(["light.a"])

        # Scene: same brightness, much warmer white (2700K vs 4450K).
        fake_hass.states.set(
            "light.a",
            FakeState(
                state="on",
                attributes={
                    "brightness": 204,  # 80% of 255
                    "color_mode": "xy",
                    "xy_color": list(kelvin_to_xy(2700)),
                },
            ),
        )
        fake_hass.states.set("light.b", FakeState(state="off"))

        switch._handle_motion_on()

        calls = fake_hass.services.async_call.call_args_list
        assert len(calls) == 1
        payload = calls[0][0][2]
        assert "light.a" not in payload["entity_id"]
        assert switch._state_ctrl.is_held("light.a")
        assert switch._state_ctrl.get_hold_reason("light.a") == "detected"

    def test_day_values_reapplied_not_held_right_after_night_entry(
        self, make_switch, fake_hass
    ):
        """A light still at day values right after day→night is re-applied.

        With ``on_enter_night="leave"`` the lights keep their day values
        through the transition. The first motion must dim them to the night
        target instead of holding them as an external scene.
        """
        switch, *_ = make_switch(day_mode=False)
        switch._state_ctrl.mark_controlled(["light.a"])

        # Simulate the day→night transition.
        night_handler = switch._get_mode_handler(MODE_NIGHT)
        night_handler.enter(MODE_DAY)

        # The light still sits at its day brightness (36% vs 80% night target).
        fake_hass.states.set(
            "light.a",
            FakeState(
                state="on",
                attributes={"brightness": 92, "color_temp": 225},  # 36% of 255
            ),
        )
        fake_hass.states.set("light.b", FakeState(state="off"))

        switch._handle_motion_on()

        calls = fake_hass.services.async_call.call_args_list
        assert len(calls) == 1
        payload = calls[0][0][2]
        assert "light.a" in payload["entity_id"]
        assert not switch._state_ctrl.is_held("light.a")

    def test_reapply_instead_of_hold_cleared_after_first_motion(
        self, make_switch, fake_hass
    ):
        """The re-apply-instead-of-hold flag is one-shot.

        After the first motion post-transition, the flag is consumed so a
        later scene divergence is held again.
        """
        switch, *_ = make_switch(day_mode=False)
        switch._state_ctrl.mark_controlled(["light.a"])

        night_handler = switch._get_mode_handler(MODE_NIGHT)
        night_handler.enter(MODE_DAY)
        assert night_handler._reapply_instead_of_hold is True

        fake_hass.states.set(
            "light.a",
            FakeState(state="on", attributes={"brightness": 92, "color_temp": 225}),
        )
        fake_hass.states.set("light.b", FakeState(state="off"))

        switch._handle_motion_on()

        assert night_handler._reapply_instead_of_hold is False

    def test_diverged_but_in_grace_period_not_held(self, make_switch, fake_hass):
        """Our own in-flight ramp (grace period) is left alone, not held."""
        switch, *_ = make_switch(day_mode=False)
        switch._state_ctrl.mark_controlled(["light.a"])
        # We just commanded this light: still inside its grace period.
        switch._manual_control_detector.mark_applied(["light.a"])

        # Still ramping toward the target: diverged for now.
        fake_hass.states.set(
            "light.a",
            FakeState(
                state="on",
                attributes={"brightness": 51, "color_temp": 225},  # 20% of 255
            ),
        )
        fake_hass.states.set("light.b", FakeState(state="off"))

        switch._handle_motion_on()

        # Not re-applied (our own ramp) and not held (grace period).
        calls = fake_hass.services.async_call.call_args_list
        assert len(calls) == 1
        payload = calls[0][0][2]
        assert "light.a" not in payload["entity_id"]
        assert not switch._state_ctrl.is_held("light.a")

    def test_small_divergence_holds_not_reapplies(self, make_switch, fake_hass):
        """A 7% brightness drift (inside adoption tolerance, outside detector's)
        is held — the hold decision and the detector now agree on one threshold.
        """
        switch, *_ = make_switch(day_mode=False)
        switch._state_ctrl.mark_controlled(["light.a"])

        # 87% vs 80% target = 7% off: > detector's 5%, < adoption's 10%.
        fake_hass.states.set(
            "light.a",
            FakeState(
                state="on",
                attributes={"brightness": 222, "color_temp": 225},
            ),
        )
        fake_hass.states.set("light.b", FakeState(state="off"))

        switch._handle_motion_on()

        calls = fake_hass.services.async_call.call_args_list
        assert len(calls) == 1
        payload = calls[0][0][2]
        assert "light.a" not in payload["entity_id"]
        assert switch._state_ctrl.is_held("light.a")
        assert switch._state_ctrl.get_hold_reason("light.a") == "detected"

    def test_within_detector_tolerance_reapplied_not_held(
        self, make_switch, fake_hass
    ):
        """A 2% drift (inside the detector's tolerance) is re-applied, not held."""
        switch, *_ = make_switch(day_mode=False)
        switch._state_ctrl.mark_controlled(["light.a"])

        # 82% vs 80% target = 2% off: inside detector tolerance, but not an
        # exact match, so it is re-applied (and never held).
        fake_hass.states.set(
            "light.a",
            FakeState(
                state="on",
                attributes={"brightness": 209, "color_temp": 225},
            ),
        )
        fake_hass.states.set("light.b", FakeState(state="off"))

        switch._handle_motion_on()

        calls = fake_hass.services.async_call.call_args_list
        assert len(calls) == 1
        payload = calls[0][0][2]
        assert "light.a" in payload["entity_id"]
        assert not switch._state_ctrl.is_held("light.a")

    def test_motion_on_cancels_off_timer(self, make_switch, fake_hass):
        """Motion ON while off-timer running → timer cancelled (TESTING.md 3.3)."""
        from datetime import datetime, timedelta, timezone

        switch, *_ = make_switch(day_mode=False)

        # Simulate a pending off-timer in the action scheduler
        run_at = datetime.now(timezone.utc) + timedelta(minutes=5)
        switch._action_scheduler.add(
            run_at=run_at,
            cancel_key=switch._config_entry.entry_id,
            source="MotionController",
            lights_for_log=["light.a"],
            callback_fn=lambda: (["light.a"], None),
            reason="motion_off",
        )
        assert len(switch._action_scheduler._entries) == 1

        switch._handle_motion_on()

        # Off-timer entry should have been cancelled
        assert len(switch._action_scheduler._entries) == 0


class TestNightPayload:
    """Tests for _build_night_payload respecting Control switches."""

    def test_control_brightness_off_excludes_brightness(
        self, make_switch, fake_hass
    ):
        """Control Brightness OFF → no brightness_pct in payload."""
        switch, ctrl_brightness, _ = make_switch(day_mode=False)
        ctrl_brightness._attr_is_on = False

        night_handler = switch._get_mode_handler("night")
        payload = night_handler.build_light_payload(["light.a"])

        assert "brightness_pct" not in payload
        assert "color_temp_kelvin" in payload

    def test_control_color_off_excludes_color(
        self, make_switch, fake_hass
    ):
        """Control Color OFF → no color_temp_kelvin in payload."""
        switch, _, ctrl_color = make_switch(day_mode=False)
        ctrl_color._attr_is_on = False

        night_handler = switch._get_mode_handler("night")
        payload = night_handler.build_light_payload(["light.a"])

        assert "brightness_pct" in payload
        assert "color_temp_kelvin" not in payload


class TestOffTimerResult:
    """Tests for _off_timer_result (called when motion-off timer fires)."""

    def _setup_controlled_lights(self, switch, fake_hass):
        """Helper: mark lights as controlled and set matching state."""
        switch._state_ctrl.mark_controlled(["light.a", "light.b"])
        # Record what we "applied" so detect_override sees matching values
        switch._manual_control_detector.mark_applied(["light.a", "light.b"])
        # Set light state matching applied values
        # 80% of 255 ≈ 204, 4450K → ~225 mired
        for lid in ["light.a", "light.b"]:
            fake_hass.states.set(
                lid,
                FakeState(
                    state="on",
                    attributes={"brightness": 204, "color_temp": 225},
                ),
            )

    def test_normal_turnoff(self, make_switch, fake_hass):
        """No blockers, no override → returns lights to turn off."""
        switch, *_ = make_switch(day_mode=False)
        self._setup_controlled_lights(switch, fake_hass)

        night_handler = switch._get_mode_handler("night")
        lights, reason = night_handler._off_timer_result()

        assert set(lights) == {"light.a", "light.b"}
        assert reason is None
        # State should be cleaned up
        assert not switch._state_ctrl.is_controlled_by_us("light.a")
        assert not switch._state_ctrl.is_controlled_by_us("light.b")

    def test_held_excluded(self, make_switch, fake_hass):
        """Held lights are excluded from the turn-off list."""
        switch, *_ = make_switch(day_mode=False)
        self._setup_controlled_lights(switch, fake_hass)
        switch._state_ctrl.set_hold(["light.a"], reason="service")

        night_handler = switch._get_mode_handler("night")
        lights, reason = night_handler._off_timer_result()

        assert lights == ["light.b"]
        assert reason is None

    def test_all_held_returns_empty(self, make_switch, fake_hass):
        """When every light is held, the off timer does nothing."""
        switch, *_ = make_switch(day_mode=False)
        self._setup_controlled_lights(switch, fake_hass)
        switch._state_ctrl.set_hold(["light.a", "light.b"], reason="service")

        night_handler = switch._get_mode_handler("night")
        lights, reason = night_handler._off_timer_result()

        assert lights == []
        assert reason == "no lights to turn off"

    def test_motion_still_active_skips(self, make_switch, fake_hass):
        """Motion still ON when timer fires → skip turn-off."""
        switch, *_ = make_switch(day_mode=False)
        self._setup_controlled_lights(switch, fake_hass)
        # Motion sensor is ON
        fake_hass.states.set(
            "binary_sensor.motion", FakeState(state="on")
        )

        night_handler = switch._get_mode_handler("night")
        lights, reason = night_handler._off_timer_result()

        assert lights == []
        assert reason == "motion/presence still active"
