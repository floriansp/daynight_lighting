"""Tests for DayNightLightingSwitch lifecycle: turn_on, turn_off, async_added_to_hass."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from tests.conftest import FakeState


# ===================================================================
#  Switch turn_on / turn_off
# ===================================================================


class TestSwitchTurnOn:
    """Tests for DayNightLightingSwitch.async_turn_on."""

    @pytest.mark.asyncio
    async def test_turn_on_starts_listeners(self, make_switch, fake_hass):
        """async_turn_on sets is_on=True, loads state, starts listeners."""
        switch, *_ = make_switch(day_mode=True)
        switch._attr_is_on = False

        # Mock async_load (it's async)
        switch._state_ctrl_instance.async_load = AsyncMock()
        fake_hass.states.set("sensor.lux", FakeState(state="50"))

        await switch.async_turn_on()

        assert switch._attr_is_on is True
        switch._state_ctrl_instance.async_load.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_turn_on_prunes_state(self, make_switch, fake_hass):
        """async_turn_on prunes stale lights from state controller."""
        switch, *_ = make_switch(day_mode=True)
        switch._attr_is_on = False
        switch._state_ctrl_instance.async_load = AsyncMock()
        fake_hass.states.set("sensor.lux", FakeState(state="50"))

        # Pre-populate state with a stale light
        switch._state_ctrl.mark_controlled(["light.a", "light.stale"])

        await switch.async_turn_on()

        # Prune should have removed light.stale (not in configured lights)
        assert "light.stale" not in switch._state_ctrl._lights_we_control

    @pytest.mark.asyncio
    async def test_turn_on_marks_lights_in_grace_period(self, make_switch, fake_hass):
        """async_turn_on shields the lights from detection during take-over."""
        switch, *_ = make_switch(day_mode=True)
        switch._attr_is_on = False
        switch._state_ctrl_instance.async_load = AsyncMock()
        fake_hass.states.set("sensor.lux", FakeState(state="50"))

        await switch.async_turn_on()

        for lid in switch.get_controlled_lights():
            assert switch._manual_control_detector.is_in_grace_period(lid) is True


class TestSwitchTurnOff:
    """Tests for DayNightLightingSwitch.async_turn_off."""

    @pytest.mark.asyncio
    async def test_turn_off_stops_listeners(self, make_switch, fake_hass):
        """async_turn_off sets is_on=False and resets transient state."""
        switch, *_ = make_switch(day_mode=True)
        fake_hass.states.set("sensor.lux", FakeState(state="50"))

        assert switch._attr_is_on is True

        await switch.async_turn_off()

        assert switch._attr_is_on is False
        # Transient state should be reset
        assert switch._last_mode is None  # Changed from _last_is_day

    @pytest.mark.asyncio
    async def test_turn_off_cancels_off_timer(self, make_switch, fake_hass):
        """async_turn_off cancels any pending off timer."""
        switch, *_ = make_switch(day_mode=False)
        fake_hass.states.set("sensor.lux", FakeState(state="50"))

        # Simulate a pending off timer entry
        from datetime import datetime, timedelta, timezone
        switch._action_scheduler._entries.append({
            "run_at": datetime.now(timezone.utc) + timedelta(minutes=5),
            "cancel_key": switch._config_entry.entry_id,
            "source": "Motion",
            "reason": "motion_off",
            "callback": lambda: ([], None),
        })
        assert len(switch._action_scheduler._entries) == 1

        await switch.async_turn_off()

        assert len(switch._action_scheduler._entries) == 0


class TestWillRemoveFromHass:
    """Tests for DayNightLightingSwitch.async_will_remove_from_hass."""

    @pytest.mark.asyncio
    async def test_removal_stops_listeners(self, make_switch, fake_hass):
        """Disabling the entry removes the entity without turning it off, so
        removal must tear down the listeners like async_turn_off does."""
        switch, *_ = make_switch(day_mode=True)
        switch._state_ctrl_instance.async_load = AsyncMock()
        fake_hass.states.set("sensor.lux", FakeState(state="50"))

        await switch.async_turn_on()
        assert switch._unsub  # listeners were started

        await switch.async_will_remove_from_hass()

        assert switch._unsub == []

    @pytest.mark.asyncio
    async def test_removal_cancels_off_timer(self, make_switch, fake_hass):
        """Removal cancels a pending motion-off timer like turn_off does."""
        switch, *_ = make_switch(day_mode=False)
        fake_hass.states.set("sensor.lux", FakeState(state="50"))

        from datetime import datetime, timedelta, timezone
        switch._action_scheduler._entries.append({
            "run_at": datetime.now(timezone.utc) + timedelta(minutes=5),
            "cancel_key": switch._config_entry.entry_id,
            "source": "Motion",
            "reason": "motion_off",
            "callback": lambda: ([], None),
        })
        assert len(switch._action_scheduler._entries) == 1

        await switch.async_will_remove_from_hass()

        assert len(switch._action_scheduler._entries) == 0


# ===================================================================
#  async_added_to_hass (RestoreEntity)
# ===================================================================


class TestAsyncAddedToHass:
    """Tests for DayNightLightingSwitch.async_added_to_hass."""

    @pytest.mark.asyncio
    async def test_restore_on_starts_listeners(self, make_switch, fake_hass):
        """Restored state=on → loads state and starts listeners."""
        switch, *_ = make_switch(day_mode=True)
        switch._attr_is_on = False
        switch._state_ctrl_instance.async_load = AsyncMock()
        fake_hass.states.set("sensor.lux", FakeState(state="50"))

        # Mock RestoreEntity: async_get_last_state returns "on"
        last_state = SimpleNamespace(state="on")
        switch.async_get_last_state = AsyncMock(return_value=last_state)

        await switch.async_added_to_hass()

        assert switch._attr_is_on is True
        switch._state_ctrl_instance.async_load.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_restore_off_does_not_start(self, make_switch, fake_hass):
        """Restored state=off → does not start listeners."""
        switch, *_ = make_switch(day_mode=True)
        switch._attr_is_on = True
        switch._state_ctrl_instance.async_load = AsyncMock()

        last_state = SimpleNamespace(state="off")
        switch.async_get_last_state = AsyncMock(return_value=last_state)

        await switch.async_added_to_hass()

        assert switch._attr_is_on is False
        switch._state_ctrl_instance.async_load.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_restore_none_keeps_default(self, make_switch, fake_hass):
        """No previous state → keeps default (current _attr_is_on)."""
        switch, *_ = make_switch(day_mode=True)
        switch._attr_is_on = True
        switch._state_ctrl_instance.async_load = AsyncMock()
        fake_hass.states.set("sensor.lux", FakeState(state="50"))

        switch.async_get_last_state = AsyncMock(return_value=None)

        await switch.async_added_to_hass()

        # Default was True and no restore → stays True, starts listeners
        assert switch._attr_is_on is True
        switch._state_ctrl_instance.async_load.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_restore_on_marks_lights_in_grace_period(self, make_switch, fake_hass):
        """Restored state=on shields the lights from the boot-restore race."""
        switch, *_ = make_switch(day_mode=True)
        switch._attr_is_on = False
        switch._state_ctrl_instance.async_load = AsyncMock()
        fake_hass.states.set("sensor.lux", FakeState(state="50"))

        last_state = SimpleNamespace(state="on")
        switch.async_get_last_state = AsyncMock(return_value=last_state)

        await switch.async_added_to_hass()

        for lid in switch.get_controlled_lights():
            assert switch._manual_control_detector.is_in_grace_period(lid) is True
