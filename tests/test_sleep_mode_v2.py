"""Unit tests for Sleep Mode 2.0 (v1.4.0) - independent "go to bed" override mode."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import patch


from custom_components.daynight_lighting.const import (
    CONF_SLEEP_ENABLED,
    CONF_SLEEP_START_TIME,
    CONF_SLEEP_DURATION_MIN,
    MODE_SLEEP,
    MODE_DAY,
)
from tests.conftest import FakeState


class TestSleepEndsBehavior:
    """Tests for Sleep Mode 2.0 end behavior: lights OFF + block active."""

    def test_sleep_progress_complete_turns_lights_off(self, make_switch, fake_hass):
        """When sleep duration complete (progress >= 1.0), lights turn OFF."""
        switch, *_ = make_switch(
            options={
                "lights": ["light.a"],
                CONF_SLEEP_ENABLED: True,
                CONF_SLEEP_START_TIME: "21:00",
                CONF_SLEEP_DURATION_MIN: 60,
            },
            day_mode=True,
        )

        # Get sleep handler and start sleep mode
        sleep_handler = switch._get_mode_handler(MODE_SLEEP)
        sleep_handler._sleep_active = True
        sleep_handler._sleep_start_time = datetime(2026, 6, 15, 21, 0, 0)

        # Mock dt_util so sleep progress is complete (> 60 min elapsed)
        with patch('custom_components.daynight_lighting.handlers.sleep.dt_util') as mock_dt:
            mock_dt.now.return_value = datetime(2026, 6, 15, 22, 30, 0)  # 90 min later
            sleep_handler.tick()

        # Check that turn_off was called
        calls = fake_hass.services.async_call.call_args_list
        turn_off_calls = [c for c in calls if c[0][1] == "turn_off"]
        assert len(turn_off_calls) >= 1

        # Check that sleep block is now active
        assert sleep_handler.is_sleep_active() is False
        assert sleep_handler.is_block_active() is True

    def test_sleep_block_prevents_night_mode_tick_without_motion(self, make_switch, fake_hass):
        """Sleep block active in night mode (no motion) → tick is skipped."""
        switch, *_ = make_switch(
            options={
                "lights": ["light.a"],
                "motion_sensor": "binary_sensor.motion",
            },
            day_mode=False,  # Night mode
        )
        # No motion
        fake_hass.states.set("binary_sensor.motion", FakeState(state="off"))

        # Activate sleep block on the handler
        sleep_handler = switch._get_mode_handler(MODE_SLEEP)
        sleep_handler._sleep_block_active = True

        fake_hass.services.async_call.reset_mock()

        # Trigger tick with mocked dt_util
        with patch('custom_components.daynight_lighting.schedule.dt_util') as mock_dt:
            mock_dt.now.return_value = datetime(2026, 6, 15, 23, 0, 0)
            mock_dt.as_local.return_value = datetime(2026, 6, 15, 23, 0, 0)
            switch._handle_tick()

        # No service calls should have been made (block prevents light control)
        fake_hass.services.async_call.assert_not_called()

    def test_sleep_block_clears_on_day_mode(self, make_switch, fake_hass):
        """Sleep block clears when day mode starts (sensorless fallback)."""
        switch, *_ = make_switch(
            options={"lights": ["light.a"]},
            day_mode=True,
        )
        fake_hass.states.set("sensor.lux", FakeState(state="50"))

        # Activate sleep block on the handler
        sleep_handler = switch._get_mode_handler(MODE_SLEEP)
        sleep_handler._sleep_block_active = True

        fake_hass.services.async_call.reset_mock()

        # Trigger tick in day mode with mocked dt_util
        with patch('custom_components.daynight_lighting.schedule.dt_util') as mock_dt:
            mock_dt.now.return_value = datetime(2026, 6, 15, 10, 0, 0)
            mock_dt.as_local.return_value = datetime(2026, 6, 15, 10, 0, 0)
            switch._handle_tick()

        # Block should be cleared
        assert sleep_handler.is_block_active() is False


class TestTurnOffEndsSleep:
    """A turn_off with hold (or a foreign OFF) ends the ramp into the block."""

    def test_turn_off_hold_during_active_sleep_enters_block(self, make_switch, fake_hass):
        """turn_off (hold=true) during the wind-down jumps into the block."""
        switch, *_ = make_switch(
            options={"lights": ["light.a"]},
            day_mode=True,
        )

        sleep_handler = switch._get_mode_handler(MODE_SLEEP)
        sleep_handler._sleep_active = True
        sleep_handler._sleep_block_active = False

        switch.record_lights_turned_off_by_service(["light.a"], hold=True)

        assert sleep_handler.is_sleep_active() is False
        assert sleep_handler.is_block_active() is True

    def test_turn_off_hold_during_block_keeps_the_block(self, make_switch, fake_hass):
        """turn_off (hold=true) during the block keeps it (already dark)."""
        switch, *_ = make_switch(
            options={"lights": ["light.a"]},
            day_mode=True,
        )

        sleep_handler = switch._get_mode_handler(MODE_SLEEP)
        sleep_handler._sleep_active = False
        sleep_handler._sleep_block_active = True

        switch.record_lights_turned_off_by_service(["light.a"], hold=True)

        assert sleep_handler.is_sleep_active() is False
        assert sleep_handler.is_block_active() is True


class TestMotionClearsSleepBlock:
    """Tests for motion clearing sleep block in night mode."""

    def test_motion_clears_block_in_night_mode(self, make_switch, fake_hass):
        """Motion in night mode clears sleep block."""
        switch, *_ = make_switch(
            options={
                "lights": ["light.a"],
                "motion_sensor": "binary_sensor.motion",
            },
            day_mode=False,  # Night mode
        )

        # Set sleep block active on the handler
        sleep_handler = switch._get_mode_handler(MODE_SLEEP)
        sleep_handler._sleep_block_active = True

        # Set motion ON
        fake_hass.states.set("binary_sensor.motion", FakeState(state="on"))

        fake_hass.services.async_call.reset_mock()

        # Trigger tick with mocked dt_util
        with patch('custom_components.daynight_lighting.schedule.dt_util') as mock_dt:
            mock_dt.now.return_value = datetime(2026, 6, 15, 23, 0, 0)
            mock_dt.as_local.return_value = datetime(2026, 6, 15, 23, 0, 0)
            switch._handle_tick()

        # Block should be cleared by motion
        assert sleep_handler.is_block_active() is False


class TestInvertedConfigValidation:
    """Tests for inverted config validation (sleep_start > night_start)."""

    def test_inverted_without_duration_logs_error(self, fake_hass, caplog):
        """Inverted config without duration logs ERROR."""
        from custom_components.daynight_lighting.schedule import DayNightSchedule
        from types import SimpleNamespace

        # Create config objects
        night_mode = SimpleNamespace(
            start_time=(20, 0),  # 20:00
            start_trigger="at_time",
            motion_off_delay_min=5,
            brightness=80,
            fallback="skip",
            on_enter_night="leave",
        )
        sleep_mode = SimpleNamespace(
            enabled=True,
            start_time=(21, 15),  # 21:15 - AFTER night start (inverted)
            duration_min=None,  # Missing
            target_brightness=20,
            target_kelvin=2200,
        )
        wakeup_mode = SimpleNamespace(
            enabled=False,
            wake_time=(7, 0),
            duration_min=30,
            start_brightness=1,
        )

        import logging
        with caplog.at_level(logging.ERROR):
            sched = DayNightSchedule(fake_hass, night_mode, sleep_mode, wakeup_mode)

        # Check that ERROR was logged
        assert any("Inverted configuration" in record.message for record in caplog.records)

    def test_inverted_with_duration_logs_info(self, fake_hass, caplog):
        """Inverted config WITH duration logs INFO (allowed)."""
        from custom_components.daynight_lighting.schedule import DayNightSchedule
        from types import SimpleNamespace

        # Create config objects
        night_mode = SimpleNamespace(
            start_time=(20, 0),  # 20:00
            start_trigger="at_time",
            motion_off_delay_min=5,
            brightness=80,
            fallback="skip",
            on_enter_night="leave",
        )
        sleep_mode = SimpleNamespace(
            enabled=True,
            start_time=(21, 15),  # 21:15 - AFTER night start (inverted)
            duration_min=60,  # Explicit duration
            target_brightness=20,
            target_kelvin=2200,
        )
        wakeup_mode = SimpleNamespace(
            enabled=False,
            wake_time=(7, 0),
            duration_min=30,
            start_brightness=1,
        )

        import logging
        with caplog.at_level(logging.INFO):
            sched = DayNightSchedule(fake_hass, night_mode, sleep_mode, wakeup_mode)

        # Check that INFO was logged (config is OK)
        assert any("Inverted configuration" in record.message and "is OK" in record.message for record in caplog.records)


class TestSleepMode2Integration:
    """Integration tests for Sleep Mode 2.0 lifecycle."""

    def test_full_sleep_lifecycle(self, make_switch, fake_hass):
        """Test full sleep lifecycle: start → dim → OFF → block → clear."""
        switch, *_ = make_switch(
            options={
                "lights": ["light.a"],
                CONF_SLEEP_ENABLED: True,
                CONF_SLEEP_START_TIME: "21:00",
                CONF_SLEEP_DURATION_MIN: 1,  # 1 minute for quick test
            },
            day_mode=True,
        )

        # Get sleep handler
        sleep_handler = switch._get_mode_handler(MODE_SLEEP)

        # Initial state: no sleep active
        assert sleep_handler.is_sleep_active() is False
        assert sleep_handler.is_block_active() is False

        # Enter sleep mode
        with patch('custom_components.daynight_lighting.handlers.sleep.dt_util') as mock_dt:
            mock_dt.now.return_value = datetime(2026, 6, 15, 21, 0, 0)
            sleep_handler.enter(MODE_DAY)

        # Sleep should be active
        assert sleep_handler.is_sleep_active() is True
        assert sleep_handler.is_block_active() is False

        # Complete sleep (time > duration)
        with patch('custom_components.daynight_lighting.handlers.sleep.dt_util') as mock_dt:
            mock_dt.now.return_value = datetime(2026, 6, 15, 21, 5, 0)  # 5 min later > 1 min duration
            sleep_handler.tick()

        # Sleep should end: lights OFF, block active
        assert sleep_handler.is_sleep_active() is False
        assert sleep_handler.is_block_active() is True

        # Clear the block (e.g. by day mode or motion)
        sleep_handler.clear_block()

        # Block should be cleared
        assert sleep_handler.is_block_active() is False
