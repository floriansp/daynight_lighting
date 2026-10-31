"""Tests for auxiliary switches: ControlBrightness, ControlColor."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from custom_components.daynight_lighting.switch import (
    DayNightLightingControlBrightnessSwitch,
    DayNightLightingControlColorSwitch,
)
from custom_components.daynight_lighting.const import (
    CONF_INSTANCE_NAME,
)

from tests.conftest import FakeState, MockConfigEntry


# ===================================================================
#  ControlBrightnessSwitch
# ===================================================================


class TestControlBrightnessSwitch:
    """Tests for DayNightLightingControlBrightnessSwitch."""

    def _make_switch(self, fake_hass):
        entry = MockConfigEntry(data={CONF_INSTANCE_NAME: "Test"})
        sw = DayNightLightingControlBrightnessSwitch(entry)
        sw.hass = fake_hass
        sw.async_write_ha_state = lambda: None
        return sw

    def test_default_on(self, fake_hass):
        sw = self._make_switch(fake_hass)
        assert sw.is_on is True

    def test_unique_id(self, fake_hass):
        sw = self._make_switch(fake_hass)
        assert sw.unique_id == "test_entry-control_brightness"

    @pytest.mark.asyncio
    async def test_turn_off(self, fake_hass):
        sw = self._make_switch(fake_hass)
        await sw.async_turn_off()
        assert sw.is_on is False

    @pytest.mark.asyncio
    async def test_turn_on(self, fake_hass):
        sw = self._make_switch(fake_hass)
        sw._attr_is_on = False
        await sw.async_turn_on()
        assert sw.is_on is True

    @pytest.mark.asyncio
    async def test_restore_off(self, fake_hass):
        sw = self._make_switch(fake_hass)
        last_state = FakeState(state="off")
        sw.async_get_last_state = AsyncMock(return_value=last_state)
        await sw.async_added_to_hass()
        assert sw.is_on is False

    @pytest.mark.asyncio
    async def test_restore_on(self, fake_hass):
        sw = self._make_switch(fake_hass)
        sw._attr_is_on = False  # start off
        last_state = FakeState(state="on")
        sw.async_get_last_state = AsyncMock(return_value=last_state)
        await sw.async_added_to_hass()
        assert sw.is_on is True

    @pytest.mark.asyncio
    async def test_restore_none_keeps_default(self, fake_hass):
        sw = self._make_switch(fake_hass)
        sw.async_get_last_state = AsyncMock(return_value=None)
        await sw.async_added_to_hass()
        assert sw.is_on is True  # default


# ===================================================================
#  ControlColorSwitch
# ===================================================================


class TestControlColorSwitch:
    """Tests for DayNightLightingControlColorSwitch."""

    def _make_switch(self, fake_hass):
        entry = MockConfigEntry(data={CONF_INSTANCE_NAME: "Test"})
        sw = DayNightLightingControlColorSwitch(entry)
        sw.hass = fake_hass
        sw.async_write_ha_state = lambda: None
        return sw

    def test_default_on(self, fake_hass):
        sw = self._make_switch(fake_hass)
        assert sw.is_on is True

    def test_unique_id(self, fake_hass):
        sw = self._make_switch(fake_hass)
        assert sw.unique_id == "test_entry-control_color"

    @pytest.mark.asyncio
    async def test_turn_off(self, fake_hass):
        sw = self._make_switch(fake_hass)
        await sw.async_turn_off()
        assert sw.is_on is False

    @pytest.mark.asyncio
    async def test_turn_on(self, fake_hass):
        sw = self._make_switch(fake_hass)
        sw._attr_is_on = False
        await sw.async_turn_on()
        assert sw.is_on is True

    @pytest.mark.asyncio
    async def test_restore_off(self, fake_hass):
        sw = self._make_switch(fake_hass)
        last_state = FakeState(state="off")
        sw.async_get_last_state = AsyncMock(return_value=last_state)
        await sw.async_added_to_hass()
        assert sw.is_on is False

    @pytest.mark.asyncio
    async def test_restore_on(self, fake_hass):
        sw = self._make_switch(fake_hass)
        sw._attr_is_on = False
        last_state = FakeState(state="on")
        sw.async_get_last_state = AsyncMock(return_value=last_state)
        await sw.async_added_to_hass()
        assert sw.is_on is True
