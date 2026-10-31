"""Tests for area-based entity discovery."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch


from custom_components.daynight_lighting.area_discovery import (
    _is_group_light,
    _is_motion_sensor_by_entity_id,
    get_lights_in_area,
    get_motion_sensors_in_area,
    get_illuminance_sensors_in_area,
    is_area_based,
)
from custom_components.daynight_lighting.config import DayNightConfig


class TestIsAreaBased:
    """Tests for is_area_based() helper."""

    def test_returns_true_when_area_discovery_enabled_and_area_set(self):
        """Should return True when use_area_discovery=True and area_id is set."""
        assert is_area_based(use_area_discovery=True, area_id="kitchen") is True

    def test_returns_false_when_area_discovery_disabled(self):
        """Should return False when use_area_discovery=False."""
        assert is_area_based(use_area_discovery=False, area_id="kitchen") is False

    def test_returns_false_when_area_id_is_none(self):
        """Should return False when area_id is None."""
        assert is_area_based(use_area_discovery=True, area_id=None) is False

    def test_returns_false_when_both_disabled_and_none(self):
        """Should return False when both use_area_discovery=False and area_id=None."""
        assert is_area_based(use_area_discovery=False, area_id=None) is False


class TestIsMotionSensorByEntityId:
    """Tests for _is_motion_sensor_by_entity_id() helper."""

    def test_detects_motion_keyword(self):
        """Should detect motion in entity_id."""
        assert _is_motion_sensor_by_entity_id("binary_sensor.living_room_motion") is True

    def test_detects_presence_keyword(self):
        """Should detect presence in entity_id."""
        assert _is_motion_sensor_by_entity_id("binary_sensor.office_presence") is True

    def test_detects_occupancy_keyword(self):
        """Should detect occupancy in entity_id."""
        assert _is_motion_sensor_by_entity_id("binary_sensor.hall_occupancy") is True

    def test_detects_move_keyword(self):
        """Should detect move in entity_id."""
        assert _is_motion_sensor_by_entity_id("binary_sensor.kitchen_move") is True

    def test_detects_moving_keyword(self):
        """Should detect moving in entity_id."""
        assert _is_motion_sensor_by_entity_id("binary_sensor.garage_moving") is True

    def test_detects_still_keyword(self):
        """Should detect still in entity_id."""
        assert _is_motion_sensor_by_entity_id("binary_sensor.bedroom_still") is True

    def test_detects_stationary_keyword(self):
        """Should detect stationary in entity_id."""
        assert _is_motion_sensor_by_entity_id("binary_sensor.desk_stationary") is True

    def test_returns_false_for_non_motion_entities(self):
        """Should return False for entities without motion keywords."""
        assert _is_motion_sensor_by_entity_id("binary_sensor.door_sensor") is False
        assert _is_motion_sensor_by_entity_id("binary_sensor.window_contact") is False

    def test_returns_false_for_non_binary_sensor(self):
        """Should handle non-binary-sensor domains appropriately."""
        # Still checks the pattern regardless of domain
        assert _is_motion_sensor_by_entity_id("sensor.living_room_motion") is True


class TestGetLightsInArea:
    """Tests for get_lights_in_area()."""

    def test_returns_empty_list_when_area_id_none(self):
        """Should return empty list when area_id is None."""
        hass = MagicMock()
        assert get_lights_in_area(hass, None) == []

    def test_returns_empty_list_when_registries_none(self):
        """Should return empty list when entity/device registries are None."""
        hass = MagicMock()
        with patch(
            "custom_components.daynight_lighting.area_discovery.er", None
        ), patch("custom_components.daynight_lighting.area_discovery.dr", None):
            assert get_lights_in_area(hass, "kitchen") == []

    def test_finds_lights_in_area(self):
        """Should find lights in the specified area."""
        hass = MagicMock()

        # Mock entity registry
        entity_reg = MagicMock()
        entity_reg.entities = {
            "light.kitchen_1": SimpleNamespace(
                entity_id="light.kitchen_1",
                area_id="kitchen",
                device_id="device_kitchen_1",
                platform="hue",
                translation_key="hue_light",
            ),
            "light.kitchen_2": SimpleNamespace(
                entity_id="light.kitchen_2",
                area_id=None,  # No direct area, should check device
                device_id="device1",
                platform="hue",
                translation_key="hue_light",
            ),
            "light.living_room": SimpleNamespace(
                entity_id="light.living_room",
                area_id="living_room",
                device_id="device_living",
                platform="hue",
                translation_key="hue_light",
            ),
        }

        # Mock device registry
        device_reg = MagicMock()
        device_reg.async_get = MagicMock(
            return_value=MagicMock(area_id="kitchen")
        )

        with patch(
            "custom_components.daynight_lighting.area_discovery.er"
        ) as mock_er, patch(
            "custom_components.daynight_lighting.area_discovery.dr"
        ) as mock_dr:
            mock_er.async_get = MagicMock(return_value=entity_reg)
            mock_dr.async_get = MagicMock(return_value=device_reg)

            result = get_lights_in_area(hass, "kitchen")

        assert "light.kitchen_1" in result
        assert "light.kitchen_2" in result
        assert "light.living_room" not in result

    def test_skips_group_entities(self):
        """Should skip virtual groups (Hue rooms/zones/groups, helper groups)."""
        hass = MagicMock()

        entity_reg = MagicMock()
        entity_reg.entities = {
            # A real Hue bulb: translation_key "hue_light"
            "light.kitchen_bulb": SimpleNamespace(
                entity_id="light.kitchen_bulb",
                area_id="kitchen",
                device_id="device_bulb",
                platform="hue",
                translation_key="hue_light",
            ),
            # Hue room/zone/group: translation_key "hue_grouped_light"
            "light.kitchen_hue_zone": SimpleNamespace(
                entity_id="light.kitchen_hue_zone",
                area_id="kitchen",
                device_id="device_group",
                platform="hue",
                translation_key="hue_grouped_light",
            ),
            # Native helper group: platform group
            "light.kitchen_group": SimpleNamespace(
                entity_id="light.kitchen_group",
                area_id="kitchen",
                device_id=None,
                platform="group",
                translation_key=None,
            ),
        }

        device_reg = MagicMock()
        device_reg.async_get = MagicMock(
            return_value=MagicMock(area_id="kitchen")
        )

        with patch(
            "custom_components.daynight_lighting.area_discovery.er"
        ) as mock_er, patch(
            "custom_components.daynight_lighting.area_discovery.dr"
        ) as mock_dr:
            mock_er.async_get = MagicMock(return_value=entity_reg)
            mock_dr.async_get = MagicMock(return_value=device_reg)

            result = get_lights_in_area(hass, "kitchen")

        assert result == ["light.kitchen_bulb"]


class TestIsGroupLight:
    """Tests for _is_group_light()."""

    def test_group_platform_is_group(self):
        entity = SimpleNamespace(platform="group", translation_key=None)
        assert _is_group_light(entity) is True

    def test_hue_grouped_light_is_group(self):
        """Hue rooms/zones/groups carry translation_key 'hue_grouped_light'."""
        entity = SimpleNamespace(platform="hue", translation_key="hue_grouped_light")
        assert _is_group_light(entity) is True

    def test_physical_hue_bulb_is_not_group(self):
        entity = SimpleNamespace(platform="hue", translation_key="hue_light")
        assert _is_group_light(entity) is False


class TestGetMotionSensorsInArea:
    """Tests for get_motion_sensors_in_area()."""

    def test_returns_empty_list_when_area_id_none(self):
        """Should return empty list when area_id is None."""
        hass = MagicMock()
        assert get_motion_sensors_in_area(hass, None) == []

    def test_finds_motion_sensors_by_device_class(self):
        """Should find sensors with motion/presence device_class."""
        hass = MagicMock()

        # Mock entity registry
        entity_reg = MagicMock()
        entity_reg.entities = {
            "binary_sensor.motion1": MagicMock(
                entity_id="binary_sensor.motion1",
                area_id="kitchen",
                device_id=None,
                original_device_class="motion",
            ),
            "binary_sensor.presence1": MagicMock(
                entity_id="binary_sensor.presence1",
                area_id="kitchen",
                device_id=None,
                original_device_class="presence",
            ),
            "binary_sensor.door": MagicMock(
                entity_id="binary_sensor.door",
                area_id="kitchen",
                device_id=None,
                original_device_class="door",
            ),
        }

        device_reg = MagicMock()

        with patch(
            "custom_components.daynight_lighting.area_discovery.er"
        ) as mock_er, patch(
            "custom_components.daynight_lighting.area_discovery.dr"
        ) as mock_dr:
            mock_er.async_get = MagicMock(return_value=entity_reg)
            mock_dr.async_get = MagicMock(return_value=device_reg)

            result = get_motion_sensors_in_area(hass, "kitchen")

        assert "binary_sensor.motion1" in result
        assert "binary_sensor.presence1" in result
        assert "binary_sensor.door" not in result

    def test_finds_motion_sensors_by_entity_id_pattern(self):
        """Should find sensors with motion keywords in entity_id."""
        hass = MagicMock()

        # Mock entity registry - no device_class but has motion in name
        entity_reg = MagicMock()
        entity_reg.entities = {
            "binary_sensor.hall_motion": MagicMock(
                entity_id="binary_sensor.hall_motion",
                area_id="hallway",
                device_id=None,
                original_device_class=None,
            ),
            "binary_sensor.hall_light": MagicMock(
                entity_id="binary_sensor.hall_light",
                area_id="hallway",
                device_id=None,
                original_device_class=None,
            ),
        }

        device_reg = MagicMock()

        with patch(
            "custom_components.daynight_lighting.area_discovery.er"
        ) as mock_er, patch(
            "custom_components.daynight_lighting.area_discovery.dr"
        ) as mock_dr:
            mock_er.async_get = MagicMock(return_value=entity_reg)
            mock_dr.async_get = MagicMock(return_value=device_reg)

            result = get_motion_sensors_in_area(hass, "hallway")

        assert "binary_sensor.hall_motion" in result
        assert "binary_sensor.hall_light" not in result

    def test_removes_duplicates(self):
        """Should not include the same sensor twice if matched by both methods."""
        hass = MagicMock()

        # Same sensor matched by device_class and entity_id
        entity_reg = MagicMock()
        entity_reg.entities = {
            "binary_sensor.kitchen_motion": MagicMock(
                entity_id="binary_sensor.kitchen_motion",
                area_id="kitchen",
                device_id=None,
                original_device_class="motion",
            ),
        }

        device_reg = MagicMock()

        with patch(
            "custom_components.daynight_lighting.area_discovery.er"
        ) as mock_er, patch(
            "custom_components.daynight_lighting.area_discovery.dr"
        ) as mock_dr:
            mock_er.async_get = MagicMock(return_value=entity_reg)
            mock_dr.async_get = MagicMock(return_value=device_reg)

            result = get_motion_sensors_in_area(hass, "kitchen")

        assert result == ["binary_sensor.kitchen_motion"]

    def test_skips_our_own_motion_mirror(self):
        """Our ``motion`` binary sensor must not be discovered as a sensor.

        Its entity_id contains "motion", so it would otherwise be fed back
        into the motion input it mirrors and re-trigger the tick endlessly.
        """
        hass = MagicMock()

        entity_reg = MagicMock()
        entity_reg.entities = {
            "binary_sensor.real_motion": MagicMock(
                entity_id="binary_sensor.real_motion",
                area_id="kitchen",
                device_id=None,
                original_device_class="motion",
            ),
            "binary_sensor.kitchen_daynight_lighting_motion": MagicMock(
                entity_id="binary_sensor.kitchen_daynight_lighting_motion",
                area_id="kitchen",
                device_id=None,
                platform="daynight_lighting",
            ),
        }

        device_reg = MagicMock()

        with patch(
            "custom_components.daynight_lighting.area_discovery.er"
        ) as mock_er, patch(
            "custom_components.daynight_lighting.area_discovery.dr"
        ) as mock_dr:
            mock_er.async_get = MagicMock(return_value=entity_reg)
            mock_dr.async_get = MagicMock(return_value=device_reg)

            result = get_motion_sensors_in_area(hass, "kitchen")

        assert result == ["binary_sensor.real_motion"]


class TestGetIlluminanceSensorsInArea:
    """Tests for get_illuminance_sensors_in_area()."""

    def test_returns_empty_list_when_area_id_none(self):
        """Should return empty list when area_id is None."""
        hass = MagicMock()
        assert get_illuminance_sensors_in_area(hass, None) == []

    def test_finds_illuminance_sensors_by_device_class(self):
        """Should find sensors with illuminance device_class."""
        hass = MagicMock()

        entity_reg = MagicMock()
        entity_reg.entities = {
            "sensor.lux1": MagicMock(
                entity_id="sensor.lux1",
                area_id="kitchen",
                device_id=None,
                original_device_class="illuminance",
            ),
            "sensor.temp": MagicMock(
                entity_id="sensor.temp",
                area_id="kitchen",
                device_id=None,
                original_device_class="temperature",
            ),
        }

        device_reg = MagicMock()

        with patch(
            "custom_components.daynight_lighting.area_discovery.er"
        ) as mock_er, patch(
            "custom_components.daynight_lighting.area_discovery.dr"
        ) as mock_dr:
            mock_er.async_get = MagicMock(return_value=entity_reg)
            mock_dr.async_get = MagicMock(return_value=device_reg)

            result = get_illuminance_sensors_in_area(hass, "kitchen")

        assert "sensor.lux1" in result
        assert "sensor.temp" not in result

    def test_finds_illuminance_sensors_by_entity_id_pattern(self):
        """Should find sensors with illuminance/lux keywords in entity_id."""
        hass = MagicMock()

        entity_reg = MagicMock()
        entity_reg.entities = {
            "sensor.kitchen_lux": MagicMock(
                entity_id="sensor.kitchen_lux",
                area_id="kitchen",
                device_id=None,
                original_device_class=None,
            ),
            "sensor.kitchen_illuminance": MagicMock(
                entity_id="sensor.kitchen_illuminance",
                area_id="kitchen",
                device_id=None,
                original_device_class=None,
            ),
            "sensor.kitchen_humidity": MagicMock(
                entity_id="sensor.kitchen_humidity",
                area_id="kitchen",
                device_id=None,
                original_device_class=None,
            ),
        }

        device_reg = MagicMock()

        with patch(
            "custom_components.daynight_lighting.area_discovery.er"
        ) as mock_er, patch(
            "custom_components.daynight_lighting.area_discovery.dr"
        ) as mock_dr:
            mock_er.async_get = MagicMock(return_value=entity_reg)
            mock_dr.async_get = MagicMock(return_value=device_reg)

            result = get_illuminance_sensors_in_area(hass, "kitchen")

        assert "sensor.kitchen_lux" in result
        assert "sensor.kitchen_illuminance" in result
        assert "sensor.kitchen_humidity" not in result

    def test_skips_our_own_lux_and_illuminance_mirrors(self):
        """Our ``lux`` and ``illuminance_sensors`` mirrors must not be inputs.

        Both carry illuminance keywords (and ``lux`` even an illuminance
        device class), so they would otherwise be averaged into the LUX
        reading they mirror and re-trigger the tick in an endless loop.
        """
        hass = MagicMock()

        entity_reg = MagicMock()
        entity_reg.entities = {
            "sensor.real_lux": MagicMock(
                entity_id="sensor.real_lux",
                area_id="kitchen",
                device_id=None,
                original_device_class="illuminance",
            ),
            "sensor.kitchen_daynight_lighting_lux": MagicMock(
                entity_id="sensor.kitchen_daynight_lighting_lux",
                area_id="kitchen",
                device_id=None,
                platform="daynight_lighting",
                original_device_class="illuminance",
            ),
            "sensor.kitchen_daynight_lighting_illuminance_sensors": MagicMock(
                entity_id="sensor.kitchen_daynight_lighting_illuminance_sensors",
                area_id="kitchen",
                device_id=None,
                platform="daynight_lighting",
            ),
        }

        device_reg = MagicMock()

        with patch(
            "custom_components.daynight_lighting.area_discovery.er"
        ) as mock_er, patch(
            "custom_components.daynight_lighting.area_discovery.dr"
        ) as mock_dr:
            mock_er.async_get = MagicMock(return_value=entity_reg)
            mock_dr.async_get = MagicMock(return_value=device_reg)

            result = get_illuminance_sensors_in_area(hass, "kitchen")

        assert result == ["sensor.real_lux"]


class TestGetEffectiveLights:
    """Tests for DayNightConfig.get_effective_lights()."""

    def test_legacy_mode_returns_configured_lights(self):
        cfg = DayNightConfig(lights=["light.a", "light.b"])
        assert cfg.get_effective_lights() == ["light.a", "light.b"]

    def test_legacy_mode_falls_back_to_included_lights(self):
        """Discovery off with lights only in included_lights keeps working."""
        cfg = DayNightConfig(
            use_area_discovery=False,
            area_id="kitchen",
            lights=[],
            included_lights=["light.a"],
        )
        assert cfg.get_effective_lights() == ["light.a"]

    def test_legacy_mode_prefers_lights_over_included(self):
        """Explicit lights win over any leftover included_lights in legacy mode."""
        cfg = DayNightConfig(
            use_area_discovery=False,
            area_id="kitchen",
            lights=["light.explicit"],
            included_lights=["light.a"],
        )
        assert cfg.get_effective_lights() == ["light.explicit"]

    def test_area_mode_with_included_lights_wins(self):
        cfg = DayNightConfig(
            use_area_discovery=True, area_id="kitchen", included_lights=["light.a"]
        )
        assert cfg.get_effective_lights() == ["light.a"]

    def test_legacy_mode_deduplicates_lights_case_insensitively(self):
        """Duplicate lights (any case) collapse to the first occurrence."""
        cfg = DayNightConfig(
            lights=["light.a", "light.A", "light.b", "light.a", "light.c"],
        )
        assert cfg.get_effective_lights() == ["light.a", "light.b", "light.c"]

    def test_area_mode_deduplicates_included_lights(self):
        """Included lights are deduplicated, keeping first-seen order."""
        cfg = DayNightConfig(
            use_area_discovery=True,
            area_id="kitchen",
            included_lights=["light.b", "light.a", "light.B"],
        )
        assert cfg.get_effective_lights() == ["light.b", "light.a"]

    def test_legacy_fallback_deduplicates_included_lights(self):
        """The lights-or-included_lights fallback is deduplicated too."""
        cfg = DayNightConfig(
            use_area_discovery=False,
            area_id="kitchen",
            lights=[],
            included_lights=["light.x", "light.X", "light.y"],
        )
        assert cfg.get_effective_lights() == ["light.x", "light.y"]

    def test_area_mode_empty_included_without_hass_is_empty(self):
        cfg = DayNightConfig(use_area_discovery=True, area_id="kitchen")
        assert cfg.get_effective_lights() == []

    def test_area_mode_empty_included_discovers_real_lights(self):
        """Empty included_lights → discovered area lights, groups skipped."""
        cfg = DayNightConfig(use_area_discovery=True, area_id="kitchen")

        hass = MagicMock()
        entity_reg = MagicMock()
        entity_reg.entities = {
            "light.bulb": SimpleNamespace(
                entity_id="light.bulb",
                area_id="kitchen",
                device_id="device_bulb",
                platform="hue",
                translation_key="hue_light",
            ),
            "light.hue_zone": SimpleNamespace(
                entity_id="light.hue_zone",
                area_id="kitchen",
                device_id="device_group",
                platform="hue",
                translation_key="hue_grouped_light",
            ),
        }
        device_reg = MagicMock()
        device_reg.async_get = MagicMock(return_value=MagicMock(area_id="kitchen"))

        with patch(
            "custom_components.daynight_lighting.area_discovery.er"
        ) as mock_er, patch(
            "custom_components.daynight_lighting.area_discovery.dr"
        ) as mock_dr:
            mock_er.async_get = MagicMock(return_value=entity_reg)
            mock_dr.async_get = MagicMock(return_value=device_reg)

            result = cfg.get_effective_lights(hass)

        assert result == ["light.bulb"]


class TestExcludedMotionSensorsParsing:
    """from_ha_options parses the excluded_motion_sensors list."""

    def test_list_is_parsed(self):
        cfg = DayNightConfig.from_ha_options(
            {
                "excluded_motion_sensors": [
                    "binary_sensor.cam_motion",
                    "binary_sensor.radar_zone_1",
                ]
            }
        )
        assert cfg.excluded_motion_sensors == [
            "binary_sensor.cam_motion",
            "binary_sensor.radar_zone_1",
        ]

    def test_single_string_is_wrapped(self):
        cfg = DayNightConfig.from_ha_options(
            {"excluded_motion_sensors": "binary_sensor.cam_motion"}
        )
        assert cfg.excluded_motion_sensors == ["binary_sensor.cam_motion"]

    def test_missing_defaults_to_empty_list(self):
        cfg = DayNightConfig.from_ha_options({})
        assert cfg.excluded_motion_sensors == []
