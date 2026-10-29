"""Functional tests: Live options changes (TESTING.md section 8).

These tests verify that changes made in the HA UI take effect immediately
via ``async_options_changed`` → ``_start_listeners`` →
``_invalidate_option_caches``, without requiring a switch OFF/ON.
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import patch


from tests.conftest import FakeState


class TestLightsChangeInUI:
    """TESTING.md 8.1: Add/remove lights → takes effect immediately."""

    def test_lights_added_used_immediately(self, make_switch, fake_hass):
        """Add light.c in UI → next apply targets all three lights."""
        switch, *_ = make_switch(
            options={"lights": ["light.a"]}, day_mode=True
        )
        fake_hass.states.set("sensor.lux", FakeState(state="50"))

        # Initial apply → only light.a
        day_handler = switch._get_mode_handler("day")
        day_handler._apply_day_mode()
        calls = fake_hass.services.async_call.call_args_list
        assert calls[0][0][2]["entity_id"] == ["light.a"]
        fake_hass.services.async_call.reset_mock()

        # --- Simulate UI change: add light.b and light.c ---
        switch._config_entry.options = {
            **switch._config_entry.options,
            "lights": ["light.a", "light.b", "light.c"],
        }

        # async_options_changed → _start_listeners → initial apply
        switch.async_options_changed()

        # The initial apply (day mode) should target all three lights
        turn_on_calls = [
            c for c in fake_hass.services.async_call.call_args_list
            if c[0][1] == "turn_on"
        ]
        assert len(turn_on_calls) >= 1
        assert set(turn_on_calls[-1][0][2]["entity_id"]) == {
            "light.a",
            "light.b",
            "light.c",
        }

    def test_lights_removed_used_immediately(self, make_switch, fake_hass):
        """Remove light.b in UI → next apply targets only light.a."""
        switch, *_ = make_switch(
            options={"lights": ["light.a", "light.b"]}, day_mode=True
        )
        fake_hass.states.set("sensor.lux", FakeState(state="50"))

        # Initial apply → light.a + light.b
        day_handler = switch._get_mode_handler("day")
        day_handler._apply_day_mode()
        calls = fake_hass.services.async_call.call_args_list
        assert set(calls[0][0][2]["entity_id"]) == {"light.a", "light.b"}
        fake_hass.services.async_call.reset_mock()

        # --- Simulate UI change: remove light.b ---
        switch._config_entry.options = {
            **switch._config_entry.options,
            "lights": ["light.a"],
        }

        switch.async_options_changed()

        turn_on_calls = [
            c for c in fake_hass.services.async_call.call_args_list
            if c[0][1] == "turn_on"
        ]
        assert len(turn_on_calls) >= 1
        assert turn_on_calls[-1][0][2]["entity_id"] == ["light.a"]


class TestMotionSensorChangeInUI:
    """TESTING.md 8.2: Change motion sensor → takes effect immediately."""

    def test_new_sensor_entity_used(self, make_switch, fake_hass):
        """After changing motion sensor, new entity is returned."""
        switch, *_ = make_switch(
            options={"motion_sensor": "binary_sensor.motion_old"},
            day_mode=False,
        )

        # Old sensor is active
        fake_hass.states.set(
            "binary_sensor.motion_old", FakeState(state="on")
        )
        assert switch._motion.get_motion_sensor_entity() == "binary_sensor.motion_old"
        assert switch._motion.has_motion_now() is True

        # --- Simulate UI change: new motion sensor ---
        switch._config_entry.options = {
            **switch._config_entry.options,
            "motion_sensor": "binary_sensor.motion_new",
        }

        # Mock dt_util to avoid date() issues in schedule code
        with patch(
            "custom_components.daynight_lighting.schedule.dt_util"
        ) as mock_dt:
            mock_dt.now.return_value = datetime(2026, 6, 15, 22, 0, 0)
            mock_dt.as_local.return_value = datetime(2026, 6, 15, 22, 0, 0)
            switch.async_options_changed()

        # New sensor should be used; old sensor state is irrelevant
        assert (
            switch._motion.get_motion_sensor_entity()
            == "binary_sensor.motion_new"
        )
        # New sensor has no state yet → no motion
        assert switch._motion.has_motion_now() is False

        # Set new sensor ON → motion detected
        fake_hass.states.set(
            "binary_sensor.motion_new", FakeState(state="on")
        )
        assert switch._motion.has_motion_now() is True


class TestNightStartTimeChangeInUI:
    """TESTING.md 8.3: Change night start time → next tick uses new time."""

    def test_mode_reflects_new_night_start(self, make_switch, fake_hass):
        """Changing night_start_time changes is_day_mode result."""
        switch, *_ = make_switch(
            options={
                "night_mode_start": "at_time",
                "night_mode_start_time": "23:00",
            },
            day_mode=True,  # sun above horizon
        )

        # At 22:00 with night_start=23:00 → day mode (before configured time)
        with patch(
            "custom_components.daynight_lighting.schedule.dt_util"
        ) as mock_dt:
            mock_dt.now.return_value = datetime(2026, 6, 15, 22, 0, 0)
            assert switch._is_day_mode() is True

        # --- Simulate UI change: night_start → 21:00 ---
        switch._config_entry.options = {
            **switch._config_entry.options,
            "night_mode_start_time": "21:00",
        }

        # At 22:00 with night_start=21:00 → night mode (past configured time)
        with patch(
            "custom_components.daynight_lighting.schedule.dt_util"
        ) as mock_dt:
            mock_dt.now.return_value = datetime(2026, 6, 15, 22, 0, 0)
            assert switch._is_day_mode() is False

    def test_options_changed_switches_mode(self, make_switch, fake_hass):
        """async_options_changed with new night_start → _last_is_day updated."""
        switch, *_ = make_switch(
            options={
                "night_mode_start": "at_time",
                "night_mode_start_time": "23:00",
            },
            day_mode=True,
        )
        fake_hass.states.set("sensor.lux", FakeState(state="50"))

        # Initial: 22:00, night_start=23:00 → day mode
        from custom_components.daynight_lighting.const import MODE_DAY
        with patch(
            "custom_components.daynight_lighting.schedule.dt_util"
        ) as mock_dt:
            mock_dt.now.return_value = datetime(2026, 6, 15, 22, 0, 0)
            switch.async_options_changed()

        assert switch._last_mode == MODE_DAY

        # --- Simulate UI change: night_start → 21:00 ---
        switch._config_entry.options = {
            **switch._config_entry.options,
            "night_mode_start_time": "21:00",
        }

        # Now at 22:00, night_start=21:00 → night mode
        from custom_components.daynight_lighting.const import MODE_NIGHT
        with patch(
            "custom_components.daynight_lighting.schedule.dt_util"
        ) as mock_dt:
            mock_dt.now.return_value = datetime(2026, 6, 15, 22, 0, 0)
            switch.async_options_changed()

        assert switch._last_mode == MODE_NIGHT
