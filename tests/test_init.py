"""Tests for __init__.py — async_setup, async_setup_entry, async_unload_entry, _async_options_updated."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.daynight_lighting.const import DOMAIN


# ===================================================================
#  async_setup — service registration
# ===================================================================


class TestAsyncSetup:
    """Tests for async_setup (registers services)."""

    @pytest.mark.asyncio
    async def test_registers_turn_on_and_turn_off(self):
        from custom_components.daynight_lighting import async_setup

        hass = MagicMock()
        hass.services.async_register = MagicMock()

        result = await async_setup(hass, {})

        assert result is True
        # Should register exactly two services
        calls = hass.services.async_register.call_args_list
        registered = {c[0][1] for c in calls}
        assert "turn_on" in registered
        assert "turn_off" in registered
        # All under our domain
        for c in calls:
            assert c[0][0] == DOMAIN


# ===================================================================
#  async_setup_entry
# ===================================================================


class TestAsyncSetupEntry:
    """Tests for async_setup_entry."""

    @pytest.mark.asyncio
    async def test_sets_up_domain_data(self):
        from custom_components.daynight_lighting import async_setup_entry

        hass = MagicMock()
        hass.data = {}
        hass.config_entries.async_forward_entry_setups = AsyncMock()

        config_entry = MagicMock()
        config_entry.entry_id = "test_entry"
        config_entry.async_on_unload = MagicMock()
        config_entry.add_update_listener = MagicMock(return_value=MagicMock())

        result = await async_setup_entry(hass, config_entry)

        assert result is True
        assert DOMAIN in hass.data
        assert "test_entry" in hass.data[DOMAIN]
        hass.config_entries.async_forward_entry_setups.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_registers_options_listener(self):
        from custom_components.daynight_lighting import async_setup_entry

        hass = MagicMock()
        hass.data = {}
        hass.config_entries.async_forward_entry_setups = AsyncMock()

        config_entry = MagicMock()
        config_entry.entry_id = "test_entry"
        config_entry.async_on_unload = MagicMock()
        config_entry.add_update_listener = MagicMock(return_value=MagicMock())

        await async_setup_entry(hass, config_entry)

        config_entry.add_update_listener.assert_called_once()
        config_entry.async_on_unload.assert_called_once()


# ===================================================================
#  _async_options_updated
# ===================================================================


class TestAsyncOptionsUpdated:
    """Tests for _async_options_updated."""

    @pytest.mark.asyncio
    async def test_notifies_main_switch(self):
        from custom_components.daynight_lighting import _async_options_updated

        mock_main_switch = MagicMock()
        hass = MagicMock()
        hass.data = {DOMAIN: {"entry_1": {"main_switch": mock_main_switch}}}

        config_entry = MagicMock()
        config_entry.entry_id = "entry_1"
        config_entry.title = "Test"

        await _async_options_updated(hass, config_entry)

        mock_main_switch.async_options_changed.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_main_switch_no_crash(self):
        from custom_components.daynight_lighting import _async_options_updated

        hass = MagicMock()
        hass.data = {DOMAIN: {"entry_1": {}}}

        config_entry = MagicMock()
        config_entry.entry_id = "entry_1"
        config_entry.title = "Test"

        await _async_options_updated(hass, config_entry)  # should not raise

    @pytest.mark.asyncio
    async def test_missing_domain_data_no_crash(self):
        from custom_components.daynight_lighting import _async_options_updated

        hass = MagicMock()
        hass.data = {}

        config_entry = MagicMock()
        config_entry.entry_id = "entry_1"
        config_entry.title = "Test"

        await _async_options_updated(hass, config_entry)  # should not raise


# ===================================================================
#  async_unload_entry
# ===================================================================


class TestAsyncUnloadEntry:
    """Tests for async_unload_entry."""

    @pytest.mark.asyncio
    async def test_unload_cleans_up(self):
        from custom_components.daynight_lighting import async_unload_entry

        hass = MagicMock()
        hass.data = {DOMAIN: {"entry_1": {"main_switch": MagicMock()}}}
        hass.config_entries.async_unload_platforms = AsyncMock(return_value=True)

        config_entry = MagicMock()
        config_entry.entry_id = "entry_1"

        result = await async_unload_entry(hass, config_entry)

        assert result is True
        # Every platform we set up must be unloaded again, not just switch
        from custom_components.daynight_lighting import PLATFORMS

        hass.config_entries.async_unload_platforms.assert_awaited_once_with(
            config_entry, PLATFORMS
        )
        # Single entry → domain key removed entirely (empty dict is falsy)
        assert DOMAIN not in hass.data

    @pytest.mark.asyncio
    async def test_unload_removes_domain_when_empty(self):
        from custom_components.daynight_lighting import async_unload_entry

        hass = MagicMock()
        hass.data = {DOMAIN: {"entry_1": {}}}
        hass.config_entries.async_unload_platforms = AsyncMock(return_value=True)

        config_entry = MagicMock()
        config_entry.entry_id = "entry_1"

        await async_unload_entry(hass, config_entry)

        # Domain key should be removed when no entries left
        assert DOMAIN not in hass.data

    @pytest.mark.asyncio
    async def test_unload_failure_keeps_data(self):
        from custom_components.daynight_lighting import async_unload_entry

        hass = MagicMock()
        hass.data = {DOMAIN: {"entry_1": {"main_switch": MagicMock()}}}
        hass.config_entries.async_unload_platforms = AsyncMock(return_value=False)

        config_entry = MagicMock()
        config_entry.entry_id = "entry_1"

        result = await async_unload_entry(hass, config_entry)

        assert result is False
        # Data should NOT be removed on failure
        assert "entry_1" in hass.data[DOMAIN]

    @pytest.mark.asyncio
    async def test_unload_preserves_other_entries(self):
        from custom_components.daynight_lighting import async_unload_entry

        hass = MagicMock()
        hass.data = {
            DOMAIN: {
                "entry_1": {},
                "entry_2": {"main_switch": MagicMock()},
            }
        }
        hass.config_entries.async_unload_platforms = AsyncMock(return_value=True)

        config_entry = MagicMock()
        config_entry.entry_id = "entry_1"

        await async_unload_entry(hass, config_entry)

        assert "entry_1" not in hass.data[DOMAIN]
        assert "entry_2" in hass.data[DOMAIN]
        assert DOMAIN in hass.data  # still has entries
