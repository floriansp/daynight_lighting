"""Tests for the "Block wall buttons" lock switch.

The lock is a safety switch for motion-lit rooms like a staircase: when on at
night, our services (turn_on, turn_off, adjust_brightness) are ignored so that
motion alone decides and a visitor cannot switch the lights off by accident.
"""

from __future__ import annotations

from types import SimpleNamespace

from custom_components.daynight_lighting.const import DOMAIN, MODE_DAY, MODE_NIGHT
from custom_components.daynight_lighting.control_switches import (
    DayNightLightingBlockWallButtonsSwitch,
)

from tests.conftest import FakeState


def _set_mode(switch, mode: str):
    """Force the running mode, so the schedule cannot skew these tests."""

    class _Provider:
        def get_current_mode(self) -> str:
            return mode

        def is_day_mode(self) -> bool:
            return mode == MODE_DAY

        def get_mode_and_time_for_log(self):
            return (mode, "")

    switch._schedule_override = _Provider()


def _register_block(switch, fake_hass, on: bool):
    block = DayNightLightingBlockWallButtonsSwitch(switch._config_entry)
    block.hass = fake_hass
    block.async_write_ha_state = lambda: None
    if on:
        block._attr_is_on = True
    fake_hass.data[DOMAIN][switch._config_entry.entry_id]["block_wall_buttons_switch"] = block
    return block


class TestTheGate:
    """The lock only bites at night in a motion-lit room."""

    def test_default_is_off(self):
        entry = SimpleNamespace(entry_id="e", data={}, options={})
        assert DayNightLightingBlockWallButtonsSwitch(entry)._attr_is_on is False

    def test_blocks_at_night_with_motion(self, make_switch, fake_hass):
        switch, *_ = make_switch({})
        _set_mode(switch, MODE_NIGHT)
        _register_block(switch, fake_hass, on=True)
        assert switch.is_wall_buttons_blocked() is True

    def test_does_not_block_during_day(self, make_switch, fake_hass):
        switch, *_ = make_switch({})
        _set_mode(switch, MODE_DAY)
        _register_block(switch, fake_hass, on=True)
        assert switch.is_wall_buttons_blocked() is False

    def test_does_not_block_without_a_motion_sensor(self, make_switch, fake_hass):
        switch, *_ = make_switch({"motion_sensor": None})
        _set_mode(switch, MODE_NIGHT)
        _register_block(switch, fake_hass, on=True)
        assert switch.is_wall_buttons_blocked() is False

    def test_off_never_blocks(self, make_switch, fake_hass):
        switch, *_ = make_switch({})
        _set_mode(switch, MODE_NIGHT)
        _register_block(switch, fake_hass, on=False)
        assert switch.is_wall_buttons_blocked() is False


class TestDimmingIsIgnored:
    """A blocked instance does not dim and does not touch the lights."""

    def test_adjust_brightness_is_ignored(self, make_switch, fake_hass):
        switch, *_ = make_switch({})
        _set_mode(switch, MODE_NIGHT)
        _register_block(switch, fake_hass, on=True)
        fake_hass.states.set(
            "light.a",
            FakeState(state="on", attributes={"brightness": 255}),
        )

        reason = switch.adjust_brightness(-20)

        assert "wall buttons blocked" in reason
        assert fake_hass.services.async_call.call_args_list == []
