"""Tests for manual multi-sensor configuration.

Area discovery already yields multiple motion and illuminance sensors; manual
configuration should support the same. These tests cover the list-aware entity
extraction and the ``from_ha_options`` parsing of multi-sensor values.
"""

from __future__ import annotations

from unittest.mock import patch

from custom_components.daynight_lighting.config import DayNightConfig
from custom_components.daynight_lighting.utils import extract_entity_ids

_AREA_DISCOVERY = "custom_components.daynight_lighting.area_discovery"


class TestExtractEntityIds:
    """Unit tests for extract_entity_ids."""

    def test_none_returns_empty(self):
        assert extract_entity_ids({}, "light_sensor") == []
        assert extract_entity_ids({"light_sensor": None}, "light_sensor") == []

    def test_single_string_is_wrapped(self):
        assert extract_entity_ids(
            {"light_sensor": "sensor.lux"}, "light_sensor"
        ) == ["sensor.lux"]

    def test_list_is_returned_as_is(self):
        assert extract_entity_ids(
            {"motion_sensor": ["binary_sensor.a", "binary_sensor.b"]},
            "motion_sensor",
        ) == ["binary_sensor.a", "binary_sensor.b"]

    def test_dict_entity_id_list(self):
        assert extract_entity_ids(
            {"light_sensor": {"entity_id": ["sensor.a", "sensor.b"]}},
            "light_sensor",
        ) == ["sensor.a", "sensor.b"]

    def test_invalid_entries_are_dropped(self):
        assert extract_entity_ids(
            {"light_sensor": ["sensor.ok", "", "no-domain", None, 123]},
            "light_sensor",
        ) == ["sensor.ok"]


class TestFromHaOptionsMultiSensor:
    """from_ha_options parses single and multiple manual sensors."""

    def test_multiple_sensors_parsed_into_list(self):
        cfg = DayNightConfig.from_ha_options(
            {
                "light_sensor": ["sensor.lux_a", "sensor.lux_b"],
                "motion_sensor": ["binary_sensor.m_a", "binary_sensor.m_b"],
            }
        )
        assert cfg.light_sensor == ["sensor.lux_a", "sensor.lux_b"]
        assert cfg.motion_sensor == ["binary_sensor.m_a", "binary_sensor.m_b"]

    def test_legacy_single_string_is_wrapped(self):
        cfg = DayNightConfig.from_ha_options(
            {"light_sensor": "sensor.lux", "motion_sensor": "binary_sensor.m"}
        )
        assert cfg.light_sensor == ["sensor.lux"]
        assert cfg.motion_sensor == ["binary_sensor.m"]

    def test_missing_defaults_to_none(self):
        cfg = DayNightConfig.from_ha_options({})
        assert cfg.light_sensor is None
        assert cfg.motion_sensor is None

    def test_empty_list_becomes_none(self):
        cfg = DayNightConfig.from_ha_options(
            {"light_sensor": [], "motion_sensor": []}
        )
        assert cfg.light_sensor is None
        assert cfg.motion_sensor is None


class TestResolveSensorIdsMultipleManual:
    """The main switch resolves multiple manual sensors correctly."""

    def test_non_area_returns_all_manual_sensors(self, make_switch, fake_hass):
        switch, *_ = make_switch(
            options={
                "area_id": None,
                "use_area_discovery": False,
                "motion_sensor": ["binary_sensor.m1", "binary_sensor.m2"],
                "light_sensor": ["sensor.lux1", "sensor.lux2"],
            }
        )
        assert switch._resolve_sensor_ids("motion_sensor") == [
            "binary_sensor.m1",
            "binary_sensor.m2",
        ]
        assert switch._resolve_sensor_ids("light_sensor") == [
            "sensor.lux1",
            "sensor.lux2",
        ]

    def test_area_mode_merges_manual_without_duplicates(
        self, make_switch, fake_hass
    ):
        switch, *_ = make_switch(
            options={
                "area_id": "kitchen",
                "included_lights": ["light.a"],
                "motion_sensor": [
                    "binary_sensor.kitchen_motion",
                    "binary_sensor.m2",
                ],
            }
        )
        with patch(
            f"{_AREA_DISCOVERY}.get_area_name", return_value="Kitchen"
        ), patch(
            f"{_AREA_DISCOVERY}.get_lights_in_area", return_value=["light.a"]
        ), patch(
            f"{_AREA_DISCOVERY}.get_motion_sensors_in_area",
            return_value=["binary_sensor.kitchen_motion"],
        ), patch(
            f"{_AREA_DISCOVERY}.get_illuminance_sensors_in_area", return_value=[]
        ):
            motion_ids = switch._resolve_sensor_ids("motion_sensor")

        # kitchen_motion is already discovered → not duplicated; m2 added.
        assert motion_ids == ["binary_sensor.kitchen_motion", "binary_sensor.m2"]
