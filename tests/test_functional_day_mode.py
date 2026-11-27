"""Functional tests: Day-mode orchestration in DayNightLightingSwitch."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

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
        fake_hass.states.set("light.a", FakeState(state="on"))
        fake_hass.states.set("light.b", FakeState(state="on"))
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


def test_ambient_cloud_swings_do_not_freeze(make_switch, fake_hass):
    """Strong ambient swings stay responsive when lamp feedback is impossible.

    Representative Living-room lux extrema (not a full recorded replay), with
    extra minute/observer reads exercising the same real handler and reader.
    Repeating the cloud swing produces four hysteresis reversals: without the
    handler passing the gain bound, the conservative guard would freeze here.
    """
    switch, *_ = make_switch(options={
        "lux_on": 10, "lux_off": 140, "day_min_brightness": 0,
        "day_max_brightness": 80, "lux_smoothing_samples": 3,
    }, day_mode=True)
    handler = switch._get_mode_handler("day")
    reader = handler._illuminance
    applied = []
    lux_extrema = (47, 110, 61, 95, 47, 95)
    for lux in (extreme for extreme in lux_extrema for _ in range(3)):
        fake_hass.states.set("sensor.lux", FakeState(state=str(lux)))
        handler.tick()
        before = reader.get_lux()
        handler.calculate_expected_state()
        handler.tick()  # minute tick, no measurement
        assert reader.get_lux() == before
        assert reader._flapping_freeze_until is None
        applied.append(reader.get_last_applied_brightness())
    # Each plateau drains the three-measurement smoothing buffer. These
    # turning points exceed the 3% hysteresis by a wide margin, so gain
    # plausibility (not smoothing or hysteresis alone) must prevent freezing.
    assert applied[2::3] == [57, 18, 49, 28, 57, 28]
    assert max(applied) - min(applied) > 25
    assert applied[-1] < applied[0]


def test_lamp_feedback_loop_still_freezes(make_switch, fake_hass):
    """A sensor illuminated by its own lamps still trips the safety guard."""
    switch, *_ = make_switch(options={
        "lux_on": 3, "lux_off": 11, "day_min_brightness": 0,
        "day_max_brightness": 35, "lux_smoothing_samples": 1,
    }, day_mode=True)
    handler = switch._get_mode_handler("day")
    reader = handler._illuminance
    for _ in range(30):
        brightness = reader.get_last_applied_brightness() or 0
        fake_hass.states.set("sensor.lux", FakeState(state=str(1 + 0.4 * brightness)))
        handler.tick()
        if reader._flapping_freeze_until is not None:
            break
    assert reader._flapping_freeze_until is not None
    assert not reader.should_apply_brightness(20)


# Wall time is controlled independently of sensor publication: ordinary ticks
# must not turn an old observation into a measurement after the dwell deadline.
def _dwell_day(make_switch, fake_hass, dwell=2, initially_on=False):
    """Build a day instance with known physical state and unsmoothed LUX."""
    for light in ("light.a", "light.b"):
        fake_hass.states.set(
            light, FakeState(
                state="on" if initially_on else "off",
                attributes={"brightness": 153, "color_temp_kelvin": 4000},
            ),
        )
    switch, *_ = make_switch(
        options={
            "day_min_brightness": 0,
            "lux_smoothing_samples": 1,
            "day_switch_dwell_min": dwell,
        },
        day_mode=True,
    )
    return switch, switch._get_mode_handler("day")


def test_entering_day_forgets_a_stale_applied_brightness(
    make_switch, fake_hass
) -> None:
    """Day reclaims dark lights even when both applied values match its target."""
    lights = ["light.a", "light.b"]
    for light in lights:
        fake_hass.states.set(light, FakeState(state="off"))
    switch, *_ = make_switch(
        options={
            "day_max_brightness": 80,
            "lux_smoothing_samples": 1,
            "day_switch_dwell_min": 0,  # Isolate applied memory from V28 dwell.
        },
        day_mode=True,
    )
    fake_hass.states.set("sensor.lux", FakeState(state="0.8"))
    switch._circadian.get_kelvin = Mock(return_value=(2700, -6.0))
    handler = switch._get_mode_handler("day")
    switch._illuminance.record_brightness_applied(80)
    handler._last_applied_kelvin = 2700
    assert switch._illuminance.should_apply_brightness(80) is False
    assert handler._should_apply_kelvin(2700) is False

    handler.enter(previous_mode="night")

    fake_hass.services.async_call.assert_not_called()
    handler.tick()

    fake_hass.services.async_call.assert_called_once()
    domain, service, payload = fake_hass.services.async_call.call_args[0]
    assert (domain, service) == ("light", "turn_on")
    assert payload["entity_id"] == lights
    assert payload["brightness_pct"] == 80
    assert payload["color_temp_kelvin"] == 2700


def test_day_switch_waits_for_the_dwell(make_switch, fake_hass):
    """Both transitions wait two minutes and require a new measurement."""
    switch, handler = _dwell_day(make_switch, fake_hass)
    start = datetime(2026, 11, 10, 13, 15)
    with patch("custom_components.daynight_lighting.handlers.day.datetime") as clock:
        clock.now.return_value = start
        fake_hass.states.set("sensor.lux", FakeState(state="50"))
        handler.tick()
        assert not handler.calculate_expected_state().on
        fake_hass.services.async_call.assert_not_called()  # includes colour
        clock.now.return_value = start + timedelta(seconds=119)
        fake_hass.states.set("sensor.lux", FakeState(state="49"))
        handler.tick()
        fake_hass.services.async_call.assert_not_called()
        clock.now.return_value = start + timedelta(minutes=3)
        handler.tick()  # Not a measurement, even though the deadline passed.
        fake_hass.services.async_call.assert_not_called()
        fake_hass.states.set("sensor.lux", FakeState(state="50"))
        handler.tick()
        assert fake_hass.services.async_call.call_args[0][1] == "turn_on"
        assert handler.calculate_expected_state().on
        applied = handler.calculate_expected_state().brightness_pct
        # Service mocks do not deliver HA's turn-on state feedback.
        for light in ("light.a", "light.b"):
            fake_hass.states.set(light, FakeState(state="on"))
        fake_hass.services.async_call.reset_mock()
        fake_hass.states.set("sensor.lux", FakeState(state="150"))
        handler.tick()
        assert handler.calculate_expected_state().on
        assert handler.calculate_expected_state().brightness_pct == applied
        fake_hass.services.async_call.assert_not_called()
        clock.now.return_value = start + timedelta(minutes=5)
        fake_hass.states.set("sensor.lux", FakeState(state="151"))
        handler.tick()
        assert fake_hass.services.async_call.call_args[0][1] == "turn_off"
        assert not handler.calculate_expected_state().on


def test_dwell_does_not_delay_brightness(make_switch, fake_hass):
    """In-state brightness/colour updates remain immediate, even pending off."""
    switch, handler = _dwell_day(make_switch, fake_hass, initially_on=True)
    with patch("custom_components.daynight_lighting.handlers.day.datetime") as clock:
        clock.now.return_value = datetime(2026, 11, 10, 13, 15)
        switch._circadian.get_kelvin = Mock(return_value=(4000, 30.0))
        fake_hass.states.set("sensor.lux", FakeState(state="50"))
        handler.tick()
        fake_hass.states.set("sensor.lux", FakeState(state="30"))
        handler.tick()
        payload = fake_hass.services.async_call.call_args[0][2]
        assert payload["brightness_pct"] > 60
        applied = payload["brightness_pct"]
        switch._circadian.get_kelvin = Mock(return_value=(4500, 40.0))
        fake_hass.states.set("sensor.lux", FakeState(state="150"))
        handler.tick()
        payload = fake_hass.services.async_call.call_args[0][2]
        assert payload["brightness_pct"] == applied
        assert payload["color_temp_kelvin"] == 4500
        expected = handler.calculate_expected_state()
        assert expected.on and expected.brightness_pct == applied and expected.kelvin == 4500


def test_dwell_zero_switches_immediately(make_switch, fake_hass):
    """Zero round-trips through configuration and preserves immediate switching."""
    _, handler = _dwell_day(make_switch, fake_hass, dwell=0)
    assert handler._config.switch_dwell_min == 0
    for lux, service in [(50, "turn_on"), (150, "turn_off"), (50, "turn_on")]:
        fake_hass.states.set("sensor.lux", FakeState(state=str(lux)))
        handler.tick()
        assert fake_hass.services.async_call.call_args[0][1] == service
        # Deliver the state feedback before testing the opposite transition.
        for light in ("light.a", "light.b"):
            fake_hass.states.set(
                light, FakeState(state="on" if service == "turn_on" else "off")
            )


def test_dwell_reversal_cancels_and_restarts(make_switch, fake_hass):
    """An interrupted candidate gets a full new dwell, in either direction."""
    _, handler = _dwell_day(make_switch, fake_hass)
    start = datetime(2026, 11, 10, 13, 15)
    with patch("custom_components.daynight_lighting.handlers.day.datetime") as clock:
        for seconds, lux, expected_on in [
            (0, 50, False), (110, 150, False), (120, 50, False),
            (180, 49, False), (240, 50, True),
            (250, 150, True), (360, 50, True), (370, 150, True),
            (480, 151, True), (490, 150, False),
        ]:
            clock.now.return_value = start + timedelta(seconds=seconds)
            fake_hass.states.set("sensor.lux", FakeState(state=str(lux)))
            handler.tick()
            assert handler.calculate_expected_state().on is expected_on


def test_dwell_phase_exit_discards_candidate(make_switch, fake_hass):
    """Night acts immediately; returning to day cannot inherit its old timer."""
    switch, handler = _dwell_day(make_switch, fake_hass)
    start = datetime(2026, 11, 10, 13, 15)
    with patch("custom_components.daynight_lighting.handlers.day.datetime") as clock:
        clock.now.return_value = start
        fake_hass.states.set("sensor.lux", FakeState(state="50"))
        handler.tick()
        fake_hass.services.async_call.assert_not_called()
        # Use the real coordinator to exercise exit/enter lifecycle wiring.
        switch._handle_mode_transition("day", "night")
        switch._get_mode_handler("night").handle_motion_on()
        assert fake_hass.services.async_call.call_args[0][1] == "turn_on"
        switch._handle_mode_transition("night", "day")
        fake_hass.services.async_call.reset_mock()
        clock.now.return_value = start + timedelta(minutes=3)
        fake_hass.states.set("sensor.lux", FakeState(state="49"))
        handler.tick()
        fake_hass.services.async_call.assert_not_called()
        clock.now.return_value = start + timedelta(minutes=5)
        fake_hass.states.set("sensor.lux", FakeState(state="50"))
        handler.tick()
        assert fake_hass.services.async_call.call_args[0][1] == "turn_on"


def test_new_day_handler_restarts_dwell(make_switch, fake_hass):
    """No candidate survives construction of a new integration instance."""
    start = datetime(2026, 11, 10, 13, 15)
    with patch("custom_components.daynight_lighting.handlers.day.datetime") as clock:
        clock.now.return_value = start
        _, handler = _dwell_day(make_switch, fake_hass)
        fake_hass.states.set("sensor.lux", FakeState(state="50"))
        handler.tick()
        clock.now.return_value = start + timedelta(minutes=3)
        _, handler = _dwell_day(make_switch, fake_hass)
        handler.tick()
        fake_hass.services.async_call.assert_not_called()
        clock.now.return_value = start + timedelta(minutes=5)
        fake_hass.states.set("sensor.lux", FakeState(state="50"))
        handler.tick()
        assert fake_hass.services.async_call.call_args[0][1] == "turn_on"


def test_expected_state_keeps_damped_values(make_switch, fake_hass):
    """Expected brightness and colour are applied values, not nearby targets."""
    switch, handler = _dwell_day(make_switch, fake_hass, initially_on=True)
    switch._circadian.get_kelvin = Mock(return_value=(4000, 30.0))
    fake_hass.states.set("sensor.lux", FakeState(state="50"))
    handler.tick()
    before = handler.calculate_expected_state()
    fake_hass.services.async_call.reset_mock()
    fake_hass.states.set("sensor.lux", FakeState(state="51"))
    switch._circadian.get_kelvin = Mock(return_value=(4020, 30.0))
    handler.tick()
    fake_hass.services.async_call.assert_not_called()
    after = handler.calculate_expected_state()
    assert after == before


def test_unavailable_measurement_restarts_dwell(make_switch, fake_hass):
    """An unavailable interval cannot count as uninterrupted target evidence."""
    _, handler = _dwell_day(make_switch, fake_hass)
    start = datetime(2026, 11, 10, 13, 15)
    with patch("custom_components.daynight_lighting.handlers.day.datetime") as clock:
        for seconds, lux in [(0, "50"), (110, "unavailable"), (120, "50"), (180, "49")]:
            clock.now.return_value = start + timedelta(seconds=seconds)
            fake_hass.states.set("sensor.lux", FakeState(state=lux))
            handler.tick()
            fake_hass.services.async_call.assert_not_called()
        clock.now.return_value = start + timedelta(seconds=240)
        fake_hass.states.set("sensor.lux", FakeState(state="50"))
        handler.tick()
        assert fake_hass.services.async_call.call_args[0][1] == "turn_on"


def test_forgetting_applied_values_drops_the_switch_state(make_switch, fake_hass):
    """An intervention invalidates the remembered on/off state as well.

    After somebody else has been at the lights, the state this handler
    remembers describes them no longer. The expected state must come from the
    lights again, and a candidate that was counting towards a dwell must not
    survive the intervention.
    """
    switch, handler = _dwell_day(make_switch, fake_hass)
    start = datetime(2026, 11, 10, 13, 15)
    with patch("custom_components.daynight_lighting.handlers.day.datetime") as clock:
        clock.now.return_value = start
        fake_hass.states.set("sensor.lux", FakeState(state="50"))
        handler.tick()
        # Off to on is pending; the candidate is counting towards its dwell.
        assert handler._pending_since == start
        assert not handler.calculate_expected_state().on

        handler.forget_applied_values()

        assert handler._pending_since is None
        assert handler._effective_on is None
        # The lights are still off, so the expected state follows them again
        # instead of the state from before the intervention.
        assert not handler.calculate_expected_state().on

    fake_hass.states.set("sensor.lux", FakeState(state="45"))
    handler.tick()
    fake_hass.services.async_call.assert_not_called()


def test_repeated_off_tick_sends_no_second_command(make_switch, fake_hass) -> None:
    """Bright-LUX ticks keep expecting off without perpetually renewing grace."""
    switch, handler = _dwell_day(make_switch, fake_hass, dwell=0, initially_on=True)
    lights = ["light.a", "light.b"]
    detector = switch._manual_control_detector
    start = datetime(2026, 11, 13, 12, 0, tzinfo=timezone.utc)
    with patch("custom_components.daynight_lighting.manual_control.datetime") as clock:
        clock.now.return_value = start
        fake_hass.states.set("sensor.lux", FakeState(state="150"))
        handler.tick()
        fake_hass.services.async_call.assert_called_once_with(
            "light", "turn_off", {"entity_id": lights}
        )
        assert detector._last_applied_time == dict.fromkeys(lights, start)
        # HA feedback arrives between sensor ticks; service mocks do not do it.
        for light in lights:
            fake_hass.states.set(light, FakeState(state="off"))
        clock.now.return_value = start + timedelta(seconds=6)
        fake_hass.states.set("sensor.lux", FakeState(state="151"))
        handler.tick()

        assert fake_hass.services.async_call.call_count == 1
        assert detector._last_applied_time == dict.fromkeys(lights, start)
        for light in lights:
            assert not detector.is_in_grace_period(light)
            assert switch._state_ctrl.get_expected_state(light)["on"] is False
        assert handler.calculate_expected_state().on is False
        assert switch._state_ctrl.get_lights_we_control() == set()
