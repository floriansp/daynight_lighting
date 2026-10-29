"""Tests for the adjust_brightness and reset_night_brightness services.

The service layer only resolves the entity, guards malformed calls and logs
what came back. What a step actually means depends on the mode, the sensors
and the configuration, so the instance decides that — see
``test_button_routing.py``.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.daynight_lighting.const import DOMAIN
from custom_components.daynight_lighting.services import (
    async_adjust_brightness,
    async_reset_night_brightness,
)


def _make_call(hass, step: int | None = 10, entity_id="switch.daynight_test"):
    data = {"entity_id": entity_id}
    if step is not None:
        data["step"] = step
    return SimpleNamespace(hass=hass, data=data)


def _make_instance(with_switch: bool = True, with_dial: bool = True):
    """A hass whose instance lookup resolves to a mocked instance."""
    hass = MagicMock()
    hass.services.async_call = AsyncMock()

    main_switch = MagicMock()
    main_switch.adjust_brightness.return_value = "stepped the lights"
    dial = MagicMock()

    instance_data: dict = {}
    if with_switch:
        instance_data["main_switch"] = main_switch
    if with_dial:
        instance_data["night_brightness_number"] = dial

    config_entry = SimpleNamespace(
        entry_id="e1", options={"lights": ["light.a"]}, state=None
    )
    hass.data = {DOMAIN: {"e1": instance_data}}
    return hass, main_switch, dial, config_entry


@pytest.fixture
def resolve(monkeypatch):
    """Make the entity_id lookup resolve to our fake instance."""

    def _install(config_entry, lights=None):
        monkeypatch.setattr(
            "custom_components.daynight_lighting.services._get_config_and_lights_for_entity_id",
            lambda hass, eid: (config_entry, lights or ["light.a"]),
        )

    return _install


class TestDelegation:
    """The instance decides; the service hands the step over."""

    @pytest.mark.asyncio
    async def test_the_step_is_passed_on(self, resolve):
        hass, main_switch, _, entry = _make_instance()
        resolve(entry)

        await async_adjust_brightness(_make_call(hass, step=-15))

        main_switch.adjust_brightness.assert_called_once_with(-15)

    @pytest.mark.asyncio
    async def test_the_service_touches_no_lights_itself(self, resolve):
        hass, _, _, entry = _make_instance()
        resolve(entry)

        await async_adjust_brightness(_make_call(hass, step=10))

        hass.services.async_call.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_every_named_instance_gets_the_step(self, resolve):
        hass, main_switch, _, entry = _make_instance()
        resolve(entry)
        call = SimpleNamespace(
            hass=hass,
            data={"entity_id": ["switch.a", "switch.b"], "step": 5},
        )

        await async_adjust_brightness(call)

        assert main_switch.adjust_brightness.call_count == 2


class TestGuards:
    """Malformed or unresolvable calls do nothing."""

    @pytest.mark.asyncio
    async def test_zero_step_does_nothing(self, resolve):
        hass, main_switch, _, entry = _make_instance()
        resolve(entry)

        await async_adjust_brightness(_make_call(hass, step=0))

        main_switch.adjust_brightness.assert_not_called()

    @pytest.mark.asyncio
    async def test_missing_entity_id_does_nothing(self, resolve):
        hass, main_switch, _, entry = _make_instance()
        resolve(entry)

        await async_adjust_brightness(
            SimpleNamespace(hass=hass, data={"step": 10})
        )

        main_switch.adjust_brightness.assert_not_called()

    @pytest.mark.asyncio
    async def test_an_instance_still_starting_up_is_skipped(self, resolve):
        """The entity can exist before the main switch is in hass.data."""
        hass, main_switch, _, entry = _make_instance(with_switch=False)
        resolve(entry)

        await async_adjust_brightness(_make_call(hass, step=10))

        hass.services.async_call.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_an_entity_that_is_not_ours_is_skipped(self, resolve):
        hass, main_switch, _, _ = _make_instance()
        resolve(None, lights=[])

        await async_adjust_brightness(_make_call(hass, step=10))

        main_switch.adjust_brightness.assert_not_called()


class TestReset:
    """The reset service puts the configured value back."""

    @pytest.mark.asyncio
    async def test_reset_calls_the_dial(self, resolve):
        hass, _, dial, entry = _make_instance()
        resolve(entry)

        await async_reset_night_brightness(_make_call(hass, step=None))

        dial.reset.assert_called_once()

    @pytest.mark.asyncio
    async def test_reset_without_a_dial_is_harmless(self, resolve):
        hass, _, _, entry = _make_instance(with_dial=False)
        resolve(entry)

        await async_reset_night_brightness(_make_call(hass, step=None))
