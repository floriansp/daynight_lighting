"""Tests for config_flow.py — DayNightLightingConfigFlow and OptionsFlowHandler."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.daynight_lighting.config_flow import (
    SECTION_CIRCADIAN,
    SECTION_DAY,
    SECTION_DEVICES,
    SECTION_NIGHT,
    SECTION_TRANSITIONS,
    DayNightLightingConfigFlow,
    OptionsFlowHandler,
    _flatten_sections,
)
from custom_components.daynight_lighting.const import (
    CONF_AREA_ID,
    CONF_CIRCADIAN_ENABLED,
    CONF_CIRCADIAN_MAX_KELVIN,
    CONF_CIRCADIAN_MIN_KELVIN,
    CONF_DAY_MAX_BRIGHTNESS,
    CONF_DAY_MIN_BRIGHTNESS,
    CONF_INITIAL_TRANSITION_SECONDS,
    CONF_INSTANCE_NAME,
    CONF_LIGHT_SENSOR,
    CONF_LIGHTS,
    CONF_INCLUDED_LIGHTS,
    CONF_USE_AREA_DISCOVERY,
    CONF_LUX_OFF,
    CONF_LUX_ON,
    CONF_MODE_TRANSITION_SECONDS,
    CONF_MOTION_OFF_DELAY_MIN,
    CONF_MOTION_SENSOR,
    CONF_NIGHT_BRIGHTNESS,
    CONF_NIGHT_MODE_START,
    CONF_NIGHT_MODE_START_TIME,
    CONF_ON_ENTER_NIGHT,
    CONF_TRANSITION_SECONDS,
    DEFAULT_CIRCADIAN_ENABLED,
    DEFAULT_CIRCADIAN_MAX_KELVIN,
    DEFAULT_CIRCADIAN_MIN_KELVIN,
    DEFAULT_DAY_MAX_BRIGHTNESS,
    DEFAULT_DAY_MIN_BRIGHTNESS,
    DEFAULT_INITIAL_TRANSITION_SECONDS,
    DEFAULT_LUX_OFF,
    DEFAULT_LUX_ON,
    DEFAULT_MODE_TRANSITION_SECONDS,
    DEFAULT_MOTION_OFF_DELAY_MIN,
    DEFAULT_NIGHT_BRIGHTNESS,
    DEFAULT_NIGHT_MODE_START,
    DEFAULT_NIGHT_MODE_START_TIME_STR,
    DEFAULT_ON_ENTER_NIGHT,
    DEFAULT_TRANSITION_SECONDS,
)


# ===================================================================
#  DayNightLightingConfigFlow.async_step_user
# ===================================================================


class TestConfigFlowStepUser:
    """Tests for the initial config flow step."""

    def _make_flow(self):
        """Create a flow instance with mocked HA internals."""
        flow = DayNightLightingConfigFlow.__new__(DayNightLightingConfigFlow)
        flow.hass = MagicMock()
        flow.async_set_unique_id = AsyncMock()
        flow._abort_if_unique_id_configured = MagicMock()
        flow.async_create_entry = MagicMock(return_value={"type": "create_entry"})
        flow.async_show_form = MagicMock(return_value={"type": "form"})
        return flow

    @pytest.mark.asyncio
    async def test_no_input_shows_form(self):
        """First call with no input → show form."""
        flow = self._make_flow()
        result = await flow.async_step_user(user_input=None)
        flow.async_show_form.assert_called_once()
        assert result["type"] == "form"

    @pytest.mark.asyncio
    async def test_with_name_creates_entry(self):
        """User provides instance name → create entry."""
        flow = self._make_flow()
        result = await flow.async_step_user(
            user_input={CONF_INSTANCE_NAME: "Kitchen"}
        )
        flow.async_set_unique_id.assert_awaited_once_with("kitchen")
        flow.async_create_entry.assert_called_once()
        call_kwargs = flow.async_create_entry.call_args[1]
        assert call_kwargs["title"] == "Kitchen"
        assert call_kwargs["data"][CONF_INSTANCE_NAME] == "Kitchen"

    @pytest.mark.asyncio
    async def test_with_area_and_no_name_uses_area_name(self):
        """User selects area but no name → area name used."""
        flow = self._make_flow()
        mock_area_reg = MagicMock()
        mock_area = MagicMock()
        mock_area.name = "Living Room"
        mock_area_reg.async_get.return_value = mock_area

        with patch(
            "custom_components.daynight_lighting.config_flow.ar.async_get",
            return_value=mock_area_reg,
        ):
            result = await flow.async_step_user(
                user_input={CONF_AREA_ID: "living_room", CONF_INSTANCE_NAME: ""}
            )

        flow.async_create_entry.assert_called_once()
        call_kwargs = flow.async_create_entry.call_args[1]
        assert call_kwargs["title"] == "Living Room"

    @pytest.mark.asyncio
    async def test_name_takes_priority_over_area(self):
        """User provides both area and name → name wins."""
        flow = self._make_flow()
        result = await flow.async_step_user(
            user_input={CONF_AREA_ID: "living_room", CONF_INSTANCE_NAME: "My Room"}
        )
        call_kwargs = flow.async_create_entry.call_args[1]
        assert call_kwargs["title"] == "My Room"

    @pytest.mark.asyncio
    async def test_empty_name_no_area_shows_error(self):
        """No name and no area → validation error, form shown again."""
        flow = self._make_flow()
        result = await flow.async_step_user(
            user_input={CONF_INSTANCE_NAME: ""}
        )
        flow.async_create_entry.assert_not_called()
        assert result["type"] == "form"
        errors = flow.async_show_form.call_args[1]["errors"]
        assert errors == {"base": "name_or_area_required"}

    @pytest.mark.asyncio
    async def test_name_slug_generation(self):
        """Instance name → slug used as unique_id."""
        flow = self._make_flow()
        await flow.async_step_user(
            user_input={CONF_INSTANCE_NAME: "My Living Room!"}
        )
        # "My Living Room!" → "my_living_room"
        flow.async_set_unique_id.assert_awaited_once_with("my_living_room")


# ===================================================================
#  OptionsFlowHandler.async_step_init
# ===================================================================


class TestOptionsFlowStepInit:
    """Tests for the options flow step."""

    def _make_flow(self, existing_options=None, entry_data=None):
        """Create an OptionsFlowHandler with mocked config_entry."""
        flow = OptionsFlowHandler.__new__(OptionsFlowHandler)
        flow.config_entry = MagicMock()
        flow.config_entry.options = existing_options or {}
        flow.config_entry.data = entry_data or {CONF_INSTANCE_NAME: "Test"}
        flow.async_create_entry = MagicMock(return_value={"type": "create_entry"})
        flow.async_show_form = MagicMock(return_value={"type": "form"})
        return flow

    @pytest.mark.asyncio
    async def test_no_input_shows_form(self):
        """First call → show form."""
        flow = self._make_flow()
        result = await flow.async_step_init(user_input=None)
        flow.async_show_form.assert_called_once()
        assert result["type"] == "form"

    @pytest.mark.asyncio
    async def test_with_flat_input_creates_entry(self):
        """User submits flat options (backward compat) → create entry."""
        flow = self._make_flow()
        result = await flow.async_step_init(
            user_input={CONF_LIGHTS: ["light.a"], CONF_LUX_ON: 15.0}
        )
        flow.async_create_entry.assert_called_once()
        call_kwargs = flow.async_create_entry.call_args[1]
        assert call_kwargs["data"][CONF_LIGHTS] == ["light.a"]
        assert call_kwargs["data"][CONF_LUX_ON] == 15.0

    @pytest.mark.asyncio
    async def test_with_sectioned_input_creates_entry(self):
        """User submits sectioned options (HA with section support) → flattened."""
        flow = self._make_flow()
        result = await flow.async_step_init(
            user_input={
                SECTION_DEVICES: {
                    CONF_LIGHTS: ["light.a", "light.b"],
                    CONF_LIGHT_SENSOR: "sensor.lux",
                    CONF_MOTION_SENSOR: "binary_sensor.motion",
                },
                SECTION_DAY: {
                    CONF_LUX_ON: 10.0,
                    CONF_LUX_OFF: 200.0,
                    CONF_DAY_MIN_BRIGHTNESS: 5,
                    CONF_DAY_MAX_BRIGHTNESS: 100,
                },
                SECTION_NIGHT: {
                    CONF_NIGHT_MODE_START: "at_time",
                    CONF_NIGHT_MODE_START_TIME: "22:00",
                    CONF_MOTION_OFF_DELAY_MIN: 10,
                    CONF_NIGHT_BRIGHTNESS: 30,
                    CONF_ON_ENTER_NIGHT: "turn_off",
                },
                SECTION_CIRCADIAN: {
                    CONF_CIRCADIAN_ENABLED: True,
                    CONF_CIRCADIAN_MIN_KELVIN: 2700,
                    CONF_CIRCADIAN_MAX_KELVIN: 5000,
                },
                SECTION_TRANSITIONS: {
                    CONF_TRANSITION_SECONDS: 5,
                    CONF_INITIAL_TRANSITION_SECONDS: 3,
                    CONF_MODE_TRANSITION_SECONDS: 10,
                },
            }
        )
        flow.async_create_entry.assert_called_once()
        saved = flow.async_create_entry.call_args[1]["data"]

        # All values flattened to top level
        assert saved[CONF_LIGHTS] == ["light.a", "light.b"]
        assert saved[CONF_LIGHT_SENSOR] == "sensor.lux"
        assert saved[CONF_LUX_ON] == 10.0
        assert saved[CONF_LUX_OFF] == 200.0
        assert saved[CONF_NIGHT_MODE_START] == "at_time"
        assert saved[CONF_NIGHT_MODE_START_TIME] == "22:00"
        assert saved[CONF_CIRCADIAN_ENABLED] is True
        assert saved[CONF_CIRCADIAN_MIN_KELVIN] == 2700
        assert saved[CONF_TRANSITION_SECONDS] == 5

    @pytest.mark.asyncio
    async def test_section_keys_not_in_saved_data(self):
        """Section grouping keys must NOT appear in saved options."""
        flow = self._make_flow()
        await flow.async_step_init(
            user_input={
                SECTION_DEVICES: {CONF_LIGHTS: ["light.a"]},
                SECTION_DAY: {CONF_LUX_ON: 10.0},
                SECTION_NIGHT: {CONF_NIGHT_BRIGHTNESS: 40},
                SECTION_CIRCADIAN: {CONF_CIRCADIAN_ENABLED: True},
                SECTION_TRANSITIONS: {CONF_TRANSITION_SECONDS: 5},
            }
        )
        saved = flow.async_create_entry.call_args[1]["data"]

        for section_key in (
            SECTION_DEVICES,
            SECTION_DAY,
            SECTION_NIGHT,
            SECTION_CIRCADIAN,
            SECTION_TRANSITIONS,
        ):
            assert section_key not in saved, (
                f"Section key '{section_key}' must not be stored in options"
            )

    @pytest.mark.asyncio
    async def test_preserves_instance_name(self):
        """Options merge preserves instance_name from entry data."""
        flow = self._make_flow(entry_data={CONF_INSTANCE_NAME: "Kitchen"})
        await flow.async_step_init(
            user_input={CONF_LIGHTS: ["light.a"]}
        )
        call_kwargs = flow.async_create_entry.call_args[1]
        assert call_kwargs["data"][CONF_INSTANCE_NAME] == "Kitchen"

    @pytest.mark.asyncio
    async def test_preserves_area_id(self):
        """Options merge preserves area_id."""
        flow = self._make_flow(
            existing_options={CONF_AREA_ID: "bedroom"},
            entry_data={CONF_INSTANCE_NAME: "Bedroom"},
        )
        await flow.async_step_init(
            user_input={CONF_LIGHTS: ["light.bed"]}
        )
        call_kwargs = flow.async_create_entry.call_args[1]
        assert call_kwargs["data"][CONF_AREA_ID] == "bedroom"

    @pytest.mark.asyncio
    async def test_merges_with_existing_options(self):
        """New user input is merged with existing options."""
        flow = self._make_flow(
            existing_options={CONF_LIGHTS: ["light.old"], CONF_LUX_ON: 5.0}
        )
        await flow.async_step_init(
            user_input={CONF_LIGHTS: ["light.new"]}
        )
        call_kwargs = flow.async_create_entry.call_args[1]
        # CONF_LIGHTS updated
        assert call_kwargs["data"][CONF_LIGHTS] == ["light.new"]
        # CONF_LUX_ON preserved from existing options
        assert call_kwargs["data"][CONF_LUX_ON] == 5.0

    @pytest.mark.asyncio
    async def test_merges_sectioned_with_existing_flat_options(self):
        """Sectioned input merged with existing flat options — complete scenario."""
        flow = self._make_flow(
            existing_options={
                CONF_LIGHTS: ["light.old"],
                CONF_LUX_ON: 5.0,
                CONF_NIGHT_BRIGHTNESS: 40,
            },
            entry_data={CONF_INSTANCE_NAME: "Bedroom"},
        )
        # Only change the lights in UI
        await flow.async_step_init(
            user_input={
                SECTION_DEVICES: {CONF_LIGHTS: ["light.new"]},
            }
        )
        saved = flow.async_create_entry.call_args[1]["data"]
        # Updated
        assert saved[CONF_LIGHTS] == ["light.new"]
        # Preserved from existing
        assert saved[CONF_LUX_ON] == 5.0
        assert saved[CONF_NIGHT_BRIGHTNESS] == 40
        assert saved[CONF_INSTANCE_NAME] == "Bedroom"

    @pytest.mark.asyncio
    async def test_disabling_area_discovery_carries_lights_over(self):
        """Turning off discovery carries included_lights into lights and clears the area selection."""
        flow = self._make_flow(
            existing_options={
                CONF_USE_AREA_DISCOVERY: True,
                CONF_INCLUDED_LIGHTS: ["light.a", "light.b"],
                CONF_AREA_ID: "kitchen",
            },
            entry_data={CONF_INSTANCE_NAME: "Kitchen"},
        )
        await flow.async_step_init(
            user_input={
                CONF_USE_AREA_DISCOVERY: False,
                CONF_INCLUDED_LIGHTS: ["light.a", "light.b"],
                CONF_LIGHTS: [],
            }
        )
        saved = flow.async_create_entry.call_args[1]["data"]
        assert saved[CONF_LIGHTS] == ["light.a", "light.b"]
        assert saved[CONF_INCLUDED_LIGHTS] == []

    @pytest.mark.asyncio
    async def test_disabling_area_discovery_keeps_explicit_lights(self):
        """Explicit lights win over included_lights when discovery is off."""
        flow = self._make_flow(
            existing_options={
                CONF_USE_AREA_DISCOVERY: True,
                CONF_INCLUDED_LIGHTS: ["light.a"],
                CONF_LIGHTS: ["light.explicit"],
                CONF_AREA_ID: "kitchen",
            },
            entry_data={CONF_INSTANCE_NAME: "Kitchen"},
        )
        await flow.async_step_init(
            user_input={
                CONF_USE_AREA_DISCOVERY: False,
                CONF_INCLUDED_LIGHTS: ["light.a"],
                CONF_LIGHTS: ["light.explicit"],
            }
        )
        saved = flow.async_create_entry.call_args[1]["data"]
        assert saved[CONF_LIGHTS] == ["light.explicit"]

    @pytest.mark.asyncio
    async def test_remove_configured_sensors(self):
        """Sensors can be removed after being configured."""
        # Start with configured sensors
        flow = self._make_flow(
            existing_options={
                CONF_LIGHT_SENSOR: "sensor.lux",
                CONF_MOTION_SENSOR: "binary_sensor.motion",
                CONF_LIGHTS: ["light.a"],
            }
        )
        # Remove sensors by setting to None
        await flow.async_step_init(
            user_input={
                SECTION_DEVICES: {
                    CONF_LIGHTS: ["light.a"],
                    CONF_LIGHT_SENSOR: None,
                    CONF_MOTION_SENSOR: None,
                }
            }
        )
        saved = flow.async_create_entry.call_args[1]["data"]
        # Sensors should be None, not preserved
        assert saved[CONF_LIGHT_SENSOR] is None
        assert saved[CONF_MOTION_SENSOR] is None
        # Lights should be preserved
        assert saved[CONF_LIGHTS] == ["light.a"]

    @pytest.mark.asyncio
    async def test_multiple_sensors_stored_as_list(self):
        """Multi-select sensors are stored as a list."""
        flow = self._make_flow()
        await flow.async_step_init(
            user_input={
                SECTION_DEVICES: {
                    CONF_LIGHTS: ["light.a"],
                    CONF_LIGHT_SENSOR: ["sensor.lux_a", "sensor.lux_b"],
                    CONF_MOTION_SENSOR: ["binary_sensor.m_a", "binary_sensor.m_b"],
                }
            }
        )
        saved = flow.async_create_entry.call_args[1]["data"]
        assert saved[CONF_LIGHT_SENSOR] == ["sensor.lux_a", "sensor.lux_b"]
        assert saved[CONF_MOTION_SENSOR] == ["binary_sensor.m_a", "binary_sensor.m_b"]

    @pytest.mark.asyncio
    async def test_remove_sensors_via_empty_list(self):
        """Clearing a multi-select (empty list) removes the sensors."""
        flow = self._make_flow(
            existing_options={
                CONF_LIGHT_SENSOR: ["sensor.lux"],
                CONF_MOTION_SENSOR: ["binary_sensor.motion"],
                CONF_LIGHTS: ["light.a"],
            }
        )
        await flow.async_step_init(
            user_input={
                SECTION_DEVICES: {
                    CONF_LIGHTS: ["light.a"],
                    CONF_LIGHT_SENSOR: [],
                    CONF_MOTION_SENSOR: [],
                }
            }
        )
        saved = flow.async_create_entry.call_args[1]["data"]
        assert saved[CONF_LIGHT_SENSOR] is None
        assert saved[CONF_MOTION_SENSOR] is None
        assert saved[CONF_LIGHTS] == ["light.a"]

    @pytest.mark.asyncio
    async def test_remove_sensors_by_omission(self):
        """Sensors are removed when omitted from devices section (real-world scenario)."""
        # Start with configured sensors
        flow = self._make_flow(
            existing_options={
                CONF_LIGHT_SENSOR: "sensor.lux",
                CONF_MOTION_SENSOR: "binary_sensor.motion",
                CONF_LIGHTS: ["light.a"],
            }
        )
        # User clears sensors in UI → they're omitted from submitted data
        # (EntitySelector doesn't send empty fields)
        await flow.async_step_init(
            user_input={
                SECTION_DEVICES: {
                    CONF_LIGHTS: ["light.a"],
                    # Sensor fields are completely missing (user cleared them)
                }
            }
        )
        saved = flow.async_create_entry.call_args[1]["data"]
        # Sensors should be None, not preserved from defaults
        assert saved[CONF_LIGHT_SENSOR] is None
        assert saved[CONF_MOTION_SENSOR] is None
        # Lights should be preserved
        assert saved[CONF_LIGHTS] == ["light.a"]


# ===================================================================
#  _flatten_sections — unit tests
# ===================================================================


class TestFlattenSections:
    """Unit tests for the _flatten_sections helper."""

    def test_flat_input_unchanged(self):
        """Pure flat dict passes through unchanged."""
        inp = {CONF_LIGHTS: ["light.a"], CONF_LUX_ON: 10.0}
        assert _flatten_sections(inp) == inp

    def test_nested_sections_flattened(self):
        """Section-grouped dict is flattened to top level."""
        inp = {
            SECTION_DEVICES: {CONF_LIGHTS: ["light.a"]},
            SECTION_DAY: {CONF_LUX_ON: 10.0, CONF_LUX_OFF: 200.0},
        }
        result = _flatten_sections(inp)
        assert result == {
            CONF_LIGHTS: ["light.a"],
            CONF_LUX_ON: 10.0,
            CONF_LUX_OFF: 200.0,
        }
        # Section keys must not be present
        assert SECTION_DEVICES not in result
        assert SECTION_DAY not in result

    def test_empty_input(self):
        """Empty dict returns empty dict."""
        assert _flatten_sections({}) == {}

    def test_empty_section(self):
        """Empty section dict produces no keys."""
        result = _flatten_sections({SECTION_DEVICES: {}})
        assert result == {}

    def test_mixed_flat_and_nested(self):
        """Mix of flat keys and section dicts works correctly."""
        inp = {
            "standalone_key": "value",
            SECTION_DEVICES: {CONF_LIGHTS: ["light.a"]},
        }
        result = _flatten_sections(inp)
        assert result == {"standalone_key": "value", CONF_LIGHTS: ["light.a"]}

    def test_list_values_not_treated_as_sections(self):
        """List values are NOT treated as section dicts."""
        inp = {CONF_LIGHTS: ["light.a", "light.b"]}
        result = _flatten_sections(inp)
        assert result[CONF_LIGHTS] == ["light.a", "light.b"]

    def test_bool_values_not_treated_as_sections(self):
        """Boolean values pass through correctly."""
        inp = {CONF_CIRCADIAN_ENABLED: True}
        result = _flatten_sections(inp)
        assert result[CONF_CIRCADIAN_ENABLED] is True

    def test_none_values_pass_through(self):
        """None values are preserved."""
        inp = {CONF_LIGHT_SENSOR: None}
        result = _flatten_sections(inp)
        assert result[CONF_LIGHT_SENSOR] is None

    def test_all_sections_flattened(self):
        """All five sections flatten to a single flat dict."""
        inp = {
            SECTION_DEVICES: {CONF_LIGHTS: ["light.a"]},
            SECTION_DAY: {CONF_LUX_ON: 10.0},
            SECTION_NIGHT: {CONF_NIGHT_BRIGHTNESS: 50},
            SECTION_CIRCADIAN: {CONF_CIRCADIAN_ENABLED: False},
            SECTION_TRANSITIONS: {CONF_TRANSITION_SECONDS: 3},
        }
        result = _flatten_sections(inp)
        assert result == {
            CONF_LIGHTS: ["light.a"],
            CONF_LUX_ON: 10.0,
            CONF_NIGHT_BRIGHTNESS: 50,
            CONF_CIRCADIAN_ENABLED: False,
            CONF_TRANSITION_SECONDS: 3,
        }


# ===================================================================
#  Section grouping correctness
# ===================================================================


class TestSectionGrouping:
    """Verify that all option keys belong to exactly one section."""

    # All config keys that appear in the options schema
    ALL_OPTION_KEYS = {
        # devices_sensors
        CONF_LIGHTS,
        CONF_LIGHT_SENSOR,
        CONF_MOTION_SENSOR,
        # day_mode
        CONF_LUX_ON,
        CONF_LUX_OFF,
        CONF_DAY_MIN_BRIGHTNESS,
        CONF_DAY_MAX_BRIGHTNESS,
        # night_mode
        CONF_NIGHT_MODE_START_TIME,
        CONF_NIGHT_MODE_START,
        CONF_MOTION_OFF_DELAY_MIN,
        CONF_NIGHT_BRIGHTNESS,
        CONF_ON_ENTER_NIGHT,
        # circadian
        CONF_CIRCADIAN_ENABLED,
        CONF_CIRCADIAN_MIN_KELVIN,
        CONF_CIRCADIAN_MAX_KELVIN,
        # transitions
        CONF_TRANSITION_SECONDS,
        CONF_INITIAL_TRANSITION_SECONDS,
        CONF_MODE_TRANSITION_SECONDS,
    }

    EXPECTED_SECTIONS = {
        SECTION_DEVICES: {
            CONF_LIGHTS,
            CONF_LIGHT_SENSOR,
            CONF_MOTION_SENSOR,
        },
        SECTION_DAY: {
            CONF_LUX_ON,
            CONF_LUX_OFF,
            CONF_DAY_MIN_BRIGHTNESS,
            CONF_DAY_MAX_BRIGHTNESS,
        },
        SECTION_NIGHT: {
            CONF_NIGHT_MODE_START_TIME,
            CONF_NIGHT_MODE_START,
            CONF_MOTION_OFF_DELAY_MIN,
            CONF_NIGHT_BRIGHTNESS,
            CONF_ON_ENTER_NIGHT,
        },
        SECTION_CIRCADIAN: {
            CONF_CIRCADIAN_ENABLED,
            CONF_CIRCADIAN_MIN_KELVIN,
            CONF_CIRCADIAN_MAX_KELVIN,
        },
        SECTION_TRANSITIONS: {
            CONF_TRANSITION_SECONDS,
            CONF_INITIAL_TRANSITION_SECONDS,
            CONF_MODE_TRANSITION_SECONDS,
        },
    }

    def test_all_keys_covered(self):
        """Every config option key is assigned to exactly one section."""
        covered = set()
        for keys in self.EXPECTED_SECTIONS.values():
            covered |= keys
        assert covered == self.ALL_OPTION_KEYS, (
            f"Missing keys: {self.ALL_OPTION_KEYS - covered}, "
            f"Extra keys: {covered - self.ALL_OPTION_KEYS}"
        )

    def test_no_key_in_multiple_sections(self):
        """No config key appears in more than one section."""
        seen: dict[str, str] = {}
        for section_name, keys in self.EXPECTED_SECTIONS.items():
            for key in keys:
                assert key not in seen, (
                    f"Key '{key}' in both '{seen[key]}' and '{section_name}'"
                )
                seen[key] = section_name

    def test_section_names_are_distinct(self):
        """All section constants are distinct strings."""
        names = [
            SECTION_DEVICES,
            SECTION_DAY,
            SECTION_NIGHT,
            SECTION_CIRCADIAN,
            SECTION_TRANSITIONS,
        ]
        assert len(names) == len(set(names))

    def test_roundtrip_sectioned_input_all_defaults(self):
        """All defaults go in as sectioned input, come out as flat options."""
        sectioned = {
            SECTION_DEVICES: {
                CONF_LIGHTS: [],
                CONF_LIGHT_SENSOR: None,
                CONF_MOTION_SENSOR: None,
            },
            SECTION_DAY: {
                CONF_LUX_ON: DEFAULT_LUX_ON,
                CONF_LUX_OFF: DEFAULT_LUX_OFF,
                CONF_DAY_MIN_BRIGHTNESS: DEFAULT_DAY_MIN_BRIGHTNESS,
                CONF_DAY_MAX_BRIGHTNESS: DEFAULT_DAY_MAX_BRIGHTNESS,
            },
            SECTION_NIGHT: {
                CONF_NIGHT_MODE_START_TIME: DEFAULT_NIGHT_MODE_START_TIME_STR,
                CONF_NIGHT_MODE_START: DEFAULT_NIGHT_MODE_START,
                CONF_MOTION_OFF_DELAY_MIN: DEFAULT_MOTION_OFF_DELAY_MIN,
                CONF_NIGHT_BRIGHTNESS: DEFAULT_NIGHT_BRIGHTNESS,
                CONF_ON_ENTER_NIGHT: DEFAULT_ON_ENTER_NIGHT,
            },
            SECTION_CIRCADIAN: {
                CONF_CIRCADIAN_ENABLED: DEFAULT_CIRCADIAN_ENABLED,
                CONF_CIRCADIAN_MIN_KELVIN: DEFAULT_CIRCADIAN_MIN_KELVIN,
                CONF_CIRCADIAN_MAX_KELVIN: DEFAULT_CIRCADIAN_MAX_KELVIN,
            },
            SECTION_TRANSITIONS: {
                CONF_TRANSITION_SECONDS: DEFAULT_TRANSITION_SECONDS,
                CONF_INITIAL_TRANSITION_SECONDS: DEFAULT_INITIAL_TRANSITION_SECONDS,
                CONF_MODE_TRANSITION_SECONDS: DEFAULT_MODE_TRANSITION_SECONDS,
            },
        }

        flat = _flatten_sections(sectioned)

        # Verify all keys exist in flat output
        for key in self.ALL_OPTION_KEYS:
            assert key in flat, f"Key '{key}' missing after flatten"

        # Verify no section keys leak
        for section_key in self.EXPECTED_SECTIONS:
            assert section_key not in flat


# ===================================================================
#  Fallback: _HAS_SECTIONS = False
# ===================================================================


class TestFallbackNoSections:
    """Verify the fallback path when HA does not support sections."""

    def _make_flow(self, existing_options=None, entry_data=None):
        flow = OptionsFlowHandler.__new__(OptionsFlowHandler)
        flow.config_entry = MagicMock()
        flow.config_entry.options = existing_options or {}
        flow.config_entry.data = entry_data or {CONF_INSTANCE_NAME: "Test"}
        flow.async_create_entry = MagicMock(return_value={"type": "create_entry"})
        flow.async_show_form = MagicMock(return_value={"type": "form"})
        return flow

    @pytest.mark.asyncio
    async def test_fallback_shows_form(self):
        """With _HAS_SECTIONS=False, show_form still works (flat schema)."""
        flow = self._make_flow()
        with patch(
            "custom_components.daynight_lighting.config_flow._HAS_SECTIONS", False
        ):
            result = await flow.async_step_init(user_input=None)
        flow.async_show_form.assert_called_once()
        assert result["type"] == "form"

    @pytest.mark.asyncio
    async def test_fallback_flat_input_works(self):
        """With _HAS_SECTIONS=False, flat user_input still creates entry."""
        flow = self._make_flow()
        with patch(
            "custom_components.daynight_lighting.config_flow._HAS_SECTIONS", False
        ):
            result = await flow.async_step_init(
                user_input={CONF_LIGHTS: ["light.a"], CONF_LUX_ON: 10.0}
            )
        saved = flow.async_create_entry.call_args[1]["data"]
        assert saved[CONF_LIGHTS] == ["light.a"]
        assert saved[CONF_LUX_ON] == 10.0

    @pytest.mark.asyncio
    async def test_fallback_remove_sensors_with_explicit_none(self):
        """In fallback mode, sensors can be removed by setting to None."""
        flow = self._make_flow(
            existing_options={
                CONF_LIGHT_SENSOR: "sensor.lux",
                CONF_MOTION_SENSOR: "binary_sensor.motion",
                CONF_LIGHTS: ["light.a"],
            }
        )
        with patch(
            "custom_components.daynight_lighting.config_flow._HAS_SECTIONS", False
        ):
            await flow.async_step_init(
                user_input={
                    CONF_LIGHTS: ["light.a"],
                    CONF_LIGHT_SENSOR: None,
                    CONF_MOTION_SENSOR: None,
                }
            )
        saved = flow.async_create_entry.call_args[1]["data"]
        assert saved[CONF_LIGHT_SENSOR] is None
        assert saved[CONF_MOTION_SENSOR] is None
