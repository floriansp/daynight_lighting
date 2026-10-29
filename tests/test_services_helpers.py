"""Unit tests for services.py — pure helper functions + async_turn_off bug fix."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from homeassistant.config_entries import ConfigEntryState

from custom_components.daynight_lighting.services import (
    _entity_ids_to_list,
    _get_entity_ids_from_call,
    _user_passed_brightness_or_color,
    async_calibrate_lux,
    async_turn_off,
    async_turn_on,
)
from custom_components.daynight_lighting.const import CONF_LIGHTS, DOMAIN, MAIN_SWITCH_UNIQUE_ID_SUFFIX


# ===================================================================
#  _entity_ids_to_list — normalise to list
# ===================================================================


class TestEntityIdsToList:
    """Tests for _entity_ids_to_list."""

    def test_none_returns_empty(self):
        assert _entity_ids_to_list(None) == []

    def test_single_string(self):
        assert _entity_ids_to_list("switch.living_room") == ["switch.living_room"]

    def test_list_passthrough(self):
        result = _entity_ids_to_list(["switch.a", "switch.b"])
        assert result == ["switch.a", "switch.b"]

    def test_empty_list(self):
        assert _entity_ids_to_list([]) == []

    def test_single_item_list(self):
        assert _entity_ids_to_list(["switch.a"]) == ["switch.a"]


# ===================================================================
#  _user_passed_brightness_or_color — detection
# ===================================================================


class TestUserPassedBrightnessOrColor:
    """Tests for _user_passed_brightness_or_color."""

    def test_empty_data(self):
        assert _user_passed_brightness_or_color({}) is False

    def test_brightness_pct(self):
        assert _user_passed_brightness_or_color({"brightness_pct": 80}) is True

    def test_brightness(self):
        assert _user_passed_brightness_or_color({"brightness": 200}) is True

    def test_color_temp_kelvin(self):
        assert _user_passed_brightness_or_color({"color_temp_kelvin": 4000}) is True

    def test_color_temp(self):
        assert _user_passed_brightness_or_color({"color_temp": 250}) is True

    def test_rgb_color(self):
        assert _user_passed_brightness_or_color({"rgb_color": [255, 0, 0]}) is True

    def test_none_values_ignored(self):
        """Keys present but set to None → not considered as user-passed."""
        data = {"brightness_pct": None, "color_temp_kelvin": None}
        assert _user_passed_brightness_or_color(data) is False

    def test_unrelated_keys(self):
        assert _user_passed_brightness_or_color({"entity_id": "light.a", "transition": 2}) is False

    def test_brightness_and_color(self):
        data = {"brightness_pct": 50, "color_temp_kelvin": 3000}
        assert _user_passed_brightness_or_color(data) is True

    def test_brightness_zero_is_truthy(self):
        """brightness_pct=0 is not None, so it's detected as user-passed."""
        assert _user_passed_brightness_or_color({"brightness_pct": 0}) is True


# ===================================================================
#  _get_entity_ids_from_call — ServiceCall parsing
# ===================================================================


class TestGetEntityIdsFromCall:
    """Tests for _get_entity_ids_from_call."""

    @staticmethod
    def _make_call(data: dict[str, Any]) -> SimpleNamespace:
        """Create a minimal stand-in for ServiceCall."""
        return SimpleNamespace(data=data)

    def test_entity_id_string(self):
        call = self._make_call({"entity_id": "switch.living_room"})
        assert _get_entity_ids_from_call(call) == ["switch.living_room"]

    def test_entity_id_list(self):
        call = self._make_call({"entity_id": ["switch.a", "switch.b"]})
        assert _get_entity_ids_from_call(call) == ["switch.a", "switch.b"]

    def test_target_entity_id(self):
        """HA UI sends entity_id inside target dict."""
        call = self._make_call({"target": {"entity_id": "switch.living_room"}})
        assert _get_entity_ids_from_call(call) == ["switch.living_room"]

    def test_target_entity_id_list(self):
        call = self._make_call({"target": {"entity_id": ["switch.a", "switch.b"]}})
        assert _get_entity_ids_from_call(call) == ["switch.a", "switch.b"]

    def test_no_entity_id(self):
        call = self._make_call({})
        assert _get_entity_ids_from_call(call) == []

    def test_entity_id_none(self):
        call = self._make_call({"entity_id": None})
        assert _get_entity_ids_from_call(call) == []

    def test_entity_id_takes_priority_over_target(self):
        """entity_id in data is checked first, target only as fallback."""
        call = self._make_call({
            "entity_id": "switch.direct",
            "target": {"entity_id": "switch.from_target"},
        })
        assert _get_entity_ids_from_call(call) == ["switch.direct"]

    def test_target_empty_entity_id(self):
        call = self._make_call({"target": {"entity_id": None}})
        assert _get_entity_ids_from_call(call) == []

    def test_target_without_entity_id_key(self):
        call = self._make_call({"target": {"area_id": "living_room"}})
        assert _get_entity_ids_from_call(call) == []


# ===================================================================
#  async_turn_off — regression test for NameError bug fix
# ===================================================================


class TestAsyncTurnOff:
    """Regression tests for async_turn_off (previously had NameError on config_entry)."""

    @staticmethod
    def _make_service_call(hass, data: dict[str, Any]) -> SimpleNamespace:
        """Create a minimal ServiceCall stand-in."""
        return SimpleNamespace(hass=hass, data=data)

    @pytest.mark.asyncio
    async def test_turn_off_calls_record_lights_turned_off(self):
        """After fix: config_entry is resolved, record_lights_turned_off_by_service is called."""
        # Setup mocks
        hass = MagicMock()
        hass.services.async_call = AsyncMock()

        # Mock entity registry to resolve entity_id → config_entry
        mock_entity = MagicMock()
        mock_entity.unique_id = f"test_entry{MAIN_SWITCH_UNIQUE_ID_SUFFIX}"

        mock_registry = MagicMock()
        mock_registry.async_get.return_value = mock_entity

        # Mock config entry (state must match ConfigEntryState.LOADED identity check)
        mock_config_entry = MagicMock()
        mock_config_entry.entry_id = "test_entry"
        mock_config_entry.state = ConfigEntryState.LOADED
        mock_config_entry.data = {}
        mock_config_entry.options = {CONF_LIGHTS: ["light.a", "light.b"]}

        hass.config_entries.async_get_entry.return_value = mock_config_entry

        # Mock main_switch
        mock_main_switch = MagicMock()
        mock_main_switch.is_wall_buttons_blocked.return_value = False
        hass.data = {
            DOMAIN: {
                "test_entry": {"main_switch": mock_main_switch}
            }
        }

        call = self._make_service_call(hass, {"entity_id": "switch.daynight_test"})

        with patch(
            "custom_components.daynight_lighting.services.er.async_get",
            return_value=mock_registry,
        ):
            await async_turn_off(call)

        # light.turn_off was called
        hass.services.async_call.assert_called_once_with(
            "light",
            "turn_off",
            {"entity_id": ["light.a", "light.b"]},
            blocking=True,
        )
        # record_lights_turned_off_by_service was called (this was unreachable before fix)
        mock_main_switch.record_lights_turned_off_by_service.assert_called_once_with(
            ["light.a", "light.b"], hold=False,
        )

    @pytest.mark.asyncio
    async def test_turn_off_prepares_before_light_turn_off(self):
        """Expected state OFF + grace period are set before light.turn_off runs.

        The state change event fires during the blocking service call, so
        preparing afterwards would let detection see expected=ON and flag our
        own turn-off as external control.
        """
        order: list[str] = []

        hass = MagicMock()

        async def _async_call(*args, **kwargs):
            order.append("light.turn_off")

        hass.services.async_call = AsyncMock(side_effect=_async_call)

        mock_entity = MagicMock()
        mock_entity.unique_id = f"test_entry{MAIN_SWITCH_UNIQUE_ID_SUFFIX}"
        mock_registry = MagicMock()
        mock_registry.async_get.return_value = mock_entity

        mock_config_entry = MagicMock()
        mock_config_entry.entry_id = "test_entry"
        mock_config_entry.state = ConfigEntryState.LOADED
        mock_config_entry.data = {}
        mock_config_entry.options = {CONF_LIGHTS: ["light.a", "light.b"]}
        hass.config_entries.async_get_entry.return_value = mock_config_entry

        mock_main_switch = MagicMock()
        mock_main_switch.is_wall_buttons_blocked.return_value = False
        mock_main_switch.prepare_lights_turn_off_by_service.side_effect = (
            lambda lights: order.append("prepare")
        )
        mock_main_switch.record_lights_turned_off_by_service.side_effect = (
            lambda lights, hold=False: order.append("record")
        )
        hass.data = {DOMAIN: {"test_entry": {"main_switch": mock_main_switch}}}

        call = self._make_service_call(hass, {"entity_id": "switch.daynight_test"})

        with patch(
            "custom_components.daynight_lighting.services.er.async_get",
            return_value=mock_registry,
        ):
            await async_turn_off(call)

        assert order == ["prepare", "light.turn_off", "record"]
        mock_main_switch.prepare_lights_turn_off_by_service.assert_called_once_with(
            ["light.a", "light.b"]
        )

    @pytest.mark.asyncio
    async def test_turn_off_hold_true(self):
        """hold=True records a visitor hold off until the phase ends."""
        hass = MagicMock()
        hass.services.async_call = AsyncMock()

        mock_entity = MagicMock()
        mock_entity.unique_id = f"test_entry{MAIN_SWITCH_UNIQUE_ID_SUFFIX}"
        mock_registry = MagicMock()
        mock_registry.async_get.return_value = mock_entity

        mock_config_entry = MagicMock()
        mock_config_entry.entry_id = "test_entry"
        mock_config_entry.state = ConfigEntryState.LOADED
        mock_config_entry.data = {}
        mock_config_entry.options = {CONF_LIGHTS: ["light.a", "light.b"]}
        hass.config_entries.async_get_entry.return_value = mock_config_entry

        mock_main_switch = MagicMock()
        mock_main_switch.is_wall_buttons_blocked.return_value = False
        hass.data = {DOMAIN: {"test_entry": {"main_switch": mock_main_switch}}}

        call = self._make_service_call(
            hass, {"entity_id": "switch.daynight_test", "hold": True}
        )

        with patch(
            "custom_components.daynight_lighting.services.er.async_get",
            return_value=mock_registry,
        ):
            await async_turn_off(call)

        mock_main_switch.record_lights_turned_off_by_service.assert_called_once_with(
            ["light.a", "light.b"], hold=True,
        )

    @pytest.mark.asyncio
    async def test_turn_off_no_entity_id_returns_early(self):
        """No entity_id → warning, no crash."""
        hass = MagicMock()
        hass.services.async_call = AsyncMock()
        call = self._make_service_call(hass, {})
        await async_turn_off(call)
        hass.services.async_call.assert_not_called()

    @pytest.mark.asyncio
    async def test_turn_off_invalid_entity_skipped(self):
        """Unresolvable entity_id → warning, no crash."""
        hass = MagicMock()
        hass.services.async_call = AsyncMock()

        mock_registry = MagicMock()
        mock_registry.async_get.return_value = None  # entity not found

        call = self._make_service_call(hass, {"entity_id": "switch.nonexistent"})

        with patch(
            "custom_components.daynight_lighting.services.er.async_get",
            return_value=mock_registry,
        ):
            await async_turn_off(call)

        hass.services.async_call.assert_not_called()


# ===================================================================
#  async_turn_on — service handler tests
# ===================================================================


class TestAsyncTurnOn:
    """Tests for the async_turn_on service handler."""

    @staticmethod
    def _make_service_call(hass, data: dict[str, Any]) -> SimpleNamespace:
        return SimpleNamespace(hass=hass, data=data)

    @staticmethod
    def _setup_hass_for_resolve(lights=None):
        """Create a hass mock that resolves entity_id → config_entry + lights."""
        hass = MagicMock()
        hass.services.async_call = AsyncMock()

        mock_entity = MagicMock()
        mock_entity.unique_id = f"test_entry{MAIN_SWITCH_UNIQUE_ID_SUFFIX}"

        mock_registry = MagicMock()
        mock_registry.async_get.return_value = mock_entity

        mock_config_entry = MagicMock()
        mock_config_entry.entry_id = "test_entry"
        mock_config_entry.state = ConfigEntryState.LOADED
        mock_config_entry.data = {}
        mock_config_entry.options = {CONF_LIGHTS: lights or ["light.a", "light.b"]}

        mock_main_switch = MagicMock()
        mock_main_switch.get_desired_turn_on_params.return_value = {
            "brightness_pct": 60,
            "color_temp_kelvin": 4000,
        }
        mock_main_switch.is_wall_buttons_blocked.return_value = False

        hass.data = {
            DOMAIN: {
                "test_entry": {
                    "main_switch": mock_main_switch,
                }
            }
        }
        hass.config_entries.async_get_entry.return_value = mock_config_entry

        return hass, mock_registry, mock_main_switch

    @pytest.mark.asyncio
    async def test_turn_on_no_entity_id_returns_early(self):
        """No entity_id → warning, no service call."""
        hass = MagicMock()
        hass.services.async_call = AsyncMock()
        call = self._make_service_call(hass, {})
        await async_turn_on(call)
        hass.services.async_call.assert_not_called()

    @pytest.mark.asyncio
    async def test_turn_on_no_brightness_merges_our_params(self):
        """No brightness/color → merges our desired params."""
        hass, registry, main_switch = self._setup_hass_for_resolve()
        call = self._make_service_call(hass, {"entity_id": "switch.daynight_test"})

        with patch(
            "custom_components.daynight_lighting.services.er.async_get",
            return_value=registry,
        ):
            await async_turn_on(call)

        # light.turn_on called with our params
        hass.services.async_call.assert_any_call(
            "light",
            "turn_on",
            {
                "entity_id": ["light.a", "light.b"],
                "brightness_pct": 60,
                "color_temp_kelvin": 4000,
            },
            blocking=True,
        )
        main_switch.get_desired_turn_on_params.assert_called_once_with(force_on=False)
        main_switch.record_lights_turned_on_by_service.assert_called_once_with(
            ["light.a", "light.b"], hold=False,
        )

    @pytest.mark.asyncio
    async def test_turn_on_prepares_before_light_turn_on(self):
        """Expected state is recorded before the blocking light.turn_on runs.

        The state change event fires during the blocking call, so preparing
        afterwards would let detection report our own change as external
        control.
        """
        order: list[Any] = []
        hass, registry, main_switch = self._setup_hass_for_resolve()

        async def _async_call(domain, service, data, **kwargs):
            order.append(("call", f"{domain}.{service}"))

        hass.services.async_call = AsyncMock(side_effect=_async_call)
        main_switch.prepare_lights_applied_by_service.side_effect = (
            lambda lights, *, on, brightness_pct=None, kelvin=None: order.append(
                ("prepare", on, brightness_pct, kelvin)
            )
        )

        call = self._make_service_call(hass, {"entity_id": "switch.daynight_test"})

        with patch(
            "custom_components.daynight_lighting.services.er.async_get",
            return_value=registry,
        ):
            await async_turn_on(call)

        assert order == [("prepare", True, 60, 4000), ("call", "light.turn_on")]
        main_switch.prepare_lights_applied_by_service.assert_called_once_with(
            ["light.a", "light.b"], on=True, brightness_pct=60, kelvin=4000
        )

    @pytest.mark.asyncio
    async def test_turn_on_records_hold_before_light_turn_on(self):
        """The hold (and off-timer cancel) is recorded before light.turn_on.

        A pending night motion-off timer could otherwise fire while
        light.turn_on awaits, switching the light straight back off before
        the hold is recorded — leaving it off but "held on".
        """
        order: list[Any] = []
        hass, registry, main_switch = self._setup_hass_for_resolve()

        async def _async_call(domain, service, data, **kwargs):
            order.append(("call", f"{domain}.{service}"))

        hass.services.async_call = AsyncMock(side_effect=_async_call)
        main_switch.record_lights_turned_on_by_service.side_effect = (
            lambda lights, hold=False: order.append("record_hold")
        )

        call = self._make_service_call(hass, {"entity_id": "switch.daynight_test"})

        with patch(
            "custom_components.daynight_lighting.services.er.async_get",
            return_value=registry,
        ):
            await async_turn_on(call)

        assert order == ["record_hold", ("call", "light.turn_on")]
        main_switch.record_lights_turned_on_by_service.assert_called_once_with(
            ["light.a", "light.b"], hold=False,
        )

    @pytest.mark.asyncio
    async def test_turn_on_zero_brightness_expects_off(self):
        """brightness_pct 0 makes the light report itself off."""
        hass, registry, main_switch = self._setup_hass_for_resolve()
        main_switch.get_desired_turn_on_params.return_value = {"brightness_pct": 0}

        call = self._make_service_call(hass, {"entity_id": "switch.daynight_test"})

        with patch(
            "custom_components.daynight_lighting.services.er.async_get",
            return_value=registry,
        ):
            await async_turn_on(call)

        main_switch.prepare_lights_applied_by_service.assert_called_once_with(
            ["light.a", "light.b"], on=False, brightness_pct=None, kelvin=None
        )

    @pytest.mark.asyncio
    async def test_turn_on_with_user_values_records_them_as_ours(self):
        """An instruction to us is not an intervention to step aside for."""
        hass, registry, main_switch = self._setup_hass_for_resolve()
        call = self._make_service_call(
            hass, {"entity_id": "switch.daynight_test", "brightness_pct": 90}
        )

        with patch(
            "custom_components.daynight_lighting.services.er.async_get",
            return_value=registry,
        ):
            await async_turn_on(call)

        main_switch.prepare_lights_applied_by_service.assert_called_once_with(
            ["light.a", "light.b"], on=True, brightness_pct=90, kelvin=None
        )

    @pytest.mark.asyncio
    async def test_turn_on_with_brightness_passes_it_through_untouched(self):
        """The user's explicit brightness is passed through, not merged with ours."""
        hass, registry, main_switch = self._setup_hass_for_resolve()
        call = self._make_service_call(
            hass, {"entity_id": "switch.daynight_test", "brightness_pct": 90}
        )

        with patch(
            "custom_components.daynight_lighting.services.er.async_get",
            return_value=registry,
        ):
            await async_turn_on(call)

        # The user's brightness is passed through untouched
        hass.services.async_call.assert_any_call(
            "light",
            "turn_on",
            {"entity_id": ["light.a", "light.b"], "brightness_pct": 90},
            blocking=True,
        )
        # Our params NOT merged
        main_switch.get_desired_turn_on_params.assert_not_called()

    @pytest.mark.asyncio
    async def test_turn_on_hold_true(self):
        """hold=True records a visitor hold, exactly as before the default."""
        hass, registry, main_switch = self._setup_hass_for_resolve()
        call = self._make_service_call(
            hass, {"entity_id": "switch.daynight_test", "hold": True}
        )

        with patch(
            "custom_components.daynight_lighting.services.er.async_get",
            return_value=registry,
        ):
            await async_turn_on(call)

        main_switch.get_desired_turn_on_params.assert_called_once_with(force_on=True)
        main_switch.record_lights_turned_on_by_service.assert_called_once_with(
            ["light.a", "light.b"], hold=True,
        )

    @pytest.mark.asyncio
    async def test_turn_on_hold_not_forwarded_to_light(self):
        """hold must be stripped before the light.turn_on payload."""
        hass, registry, main_switch = self._setup_hass_for_resolve()
        call = self._make_service_call(
            hass, {"entity_id": "switch.daynight_test", "hold": True}
        )

        with patch(
            "custom_components.daynight_lighting.services.er.async_get",
            return_value=registry,
        ):
            await async_turn_on(call)

        light_call = [
            c
            for c in hass.services.async_call.call_args_list
            if c.args[0] == "light" and c.args[1] == "turn_on"
        ][0]
        assert "hold" not in light_call.args[2]

    @pytest.mark.asyncio
    async def test_turn_on_keep_on_in_night_mode_not_forwarded_to_light(self):
        """The removed keep_on_in_night_mode key must be stripped, not forwarded.

        Regression: pre-1.19.0 wall-button automations still pass
        ``keep_on_in_night_mode: true``. Forwarding it to ``light.turn_on``
        makes the call fail ("not a valid option"), so a held light could not
        be switched back on with the wall button.
        """
        hass, registry, main_switch = self._setup_hass_for_resolve()
        call = self._make_service_call(
            hass,
            {"entity_id": "switch.daynight_test", "hold": True, "keep_on_in_night_mode": True},
        )

        with patch(
            "custom_components.daynight_lighting.services.er.async_get",
            return_value=registry,
        ):
            await async_turn_on(call)

        light_call = [
            c
            for c in hass.services.async_call.call_args_list
            if c.args[0] == "light" and c.args[1] == "turn_on"
        ][0]
        payload = light_call.args[2]
        assert "keep_on_in_night_mode" not in payload
        assert "hold" not in payload
        # The redundant flag must not disturb the hold behaviour.
        main_switch.record_lights_turned_on_by_service.assert_called_once_with(
            ["light.a", "light.b"], hold=True,
        )

    @pytest.mark.asyncio
    async def test_turn_on_invalid_entity_skipped(self):
        """Unresolvable entity_id → skipped."""
        hass = MagicMock()
        hass.services.async_call = AsyncMock()

        mock_registry = MagicMock()
        mock_registry.async_get.return_value = None

        call = self._make_service_call(hass, {"entity_id": "switch.nonexistent"})

        with patch(
            "custom_components.daynight_lighting.services.er.async_get",
            return_value=mock_registry,
        ):
            await async_turn_on(call)

        hass.services.async_call.assert_not_called()


# ===================================================================
#  async_calibrate_lux — expected state around the measurement steps
# ===================================================================


class TestAsyncCalibrateLux:
    """Calibration must not trip external control detection."""

    @pytest.mark.asyncio
    async def test_expected_state_prepared_before_each_step(self):
        """Expected state matches the values calibration sets, before it sets them."""
        order: list[Any] = []

        hass = MagicMock()

        async def _async_call(_domain, service, data, **kwargs):
            order.append(("call", service, data.get("brightness_pct")))

        hass.services.async_call = AsyncMock(side_effect=_async_call)

        entity = MagicMock()
        entity.unique_id = f"test_entry{MAIN_SWITCH_UNIQUE_ID_SUFFIX}"
        registry = MagicMock()
        registry.async_get.return_value = entity

        config_entry = MagicMock()
        config_entry.entry_id = "test_entry"
        config_entry.state = ConfigEntryState.LOADED
        config_entry.data = {}
        config_entry.options = {CONF_LIGHTS: ["light.a"]}
        hass.config_entries.async_get_entry.return_value = config_entry

        main_switch = MagicMock()
        main_switch._illuminance.get_light_sensor_entity.return_value = "sensor.lux"
        main_switch._illuminance.get_lux_raw.side_effect = [120.0, 20.0]
        main_switch.prepare_lights_applied_by_service.side_effect = (
            lambda lights, *, on, brightness_pct=None: order.append(
                ("prepare", on, brightness_pct)
            )
        )
        hass.data = {DOMAIN: {"test_entry": {"main_switch": main_switch}}}

        call = SimpleNamespace(hass=hass, data={"entity_id": "switch.daynight_test"})

        with patch(
            "custom_components.daynight_lighting.services.er.async_get",
            return_value=registry,
        ), patch(
            "custom_components.daynight_lighting.services.asyncio.sleep",
            new=AsyncMock(),
        ):
            await async_calibrate_lux(call)

        assert order == [
            ("prepare", True, 100),
            ("call", "turn_on", 100),
            ("prepare", False, None),
            ("call", "turn_off", None),
        ]
        main_switch._state_ctrl.set_lux_calibration.assert_called_once_with(100.0)
