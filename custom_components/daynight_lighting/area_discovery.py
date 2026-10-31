"""Area-based entity discovery for DayNight Lighting.

This module provides auto-discovery of lights, motion sensors, and illuminance
sensors based on Home Assistant's Area registry.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

# Registry imports - wrapped for test environment compatibility
try:
    from homeassistant.helpers import area_registry as ar
    from homeassistant.helpers import device_registry as dr
    from homeassistant.helpers import entity_registry as er
except ImportError:
    ar = None  # type: ignore[misc]
    dr = None  # type: ignore[misc]
    er = None  # type: ignore[misc]


# Motion sensor keywords to check in entity_id
MOTION_SENSOR_KEYWORDS = [
    "motion",
    "presence",
    "occupancy",
    "moving",
    "move",
    "still",
    "stationary",
]

# Illuminance sensor keywords to check in entity_id
ILLUMINANCE_SENSOR_KEYWORDS = [
    "illuminance",
    "illumination",
    "lux",
]


def _get_entity_area_id(
    entity, entity_reg, device_reg
) -> str | None:
    """Get area_id for an entity, checking entity and device registry.

    Args:
        entity: Entity registry entry
        entity_reg: Entity registry
        device_reg: Device registry

    Returns:
        Area ID or None if not assigned
    """
    # Check entity's direct area assignment
    if entity.area_id:
        return entity.area_id

    # Check device's area assignment
    if entity.device_id and device_reg:
        device = device_reg.async_get(entity.device_id)
        if device:
            return device.area_id

    return None


def _is_motion_sensor_by_entity_id(entity_id: str) -> bool:
    """Check if entity_id matches motion sensor patterns.

    Args:
        entity_id: Entity ID to check

    Returns:
        True if entity_id contains motion-related keywords
    """
    entity_id_lower = entity_id.lower()
    parts = entity_id_lower.split("_")

    for keyword in MOTION_SENSOR_KEYWORDS:
        if keyword in parts:
            return True
        if f"_{keyword}_" in entity_id_lower:
            return True
        if entity_id_lower.startswith(f"{keyword}_"):
            return True
        if entity_id_lower.endswith(f"_{keyword}"):
            return True

    return False


def _is_illuminance_sensor_by_entity_id(entity_id: str) -> bool:
    """Check if entity_id matches illuminance sensor patterns.

    Args:
        entity_id: Entity ID to check

    Returns:
        True if entity_id contains illuminance-related keywords
    """
    entity_id_lower = entity_id.lower()
    parts = entity_id_lower.split("_")

    for keyword in ILLUMINANCE_SENSOR_KEYWORDS:
        if keyword in parts:
            return True
        if f"_{keyword}_" in entity_id_lower:
            return True
        if entity_id_lower.startswith(f"{keyword}_"):
            return True
        if entity_id_lower.endswith(f"_{keyword}"):
            return True

    return False


def _is_group_light(entity) -> bool:
    """True when a light entity is a virtual group, not a physical light.

    Two kinds of group show up as ``light.*`` entities:

    * Native helper groups (``platform == "group"``).
    * Integration groups, most notably Philips Hue rooms, zones and groups.
      Hue exposes them with ``translation_key == "hue_grouped_light"`` while
      a real Hue bulb is ``"hue_light"``. Both have a device entry, so the
      translation key is the reliable signal — not the presence of a device.

    Controlling a group re-commands its member lights, and the state changes
    that follow look like external control, flipping the instance into manual
    control. Hence these must not be picked up by area discovery.
    """
    if getattr(entity, "platform", None) == "group":
        return True
    translation_key = getattr(entity, "translation_key", None)
    return bool(translation_key and translation_key.endswith("_grouped_light"))


# The platform under which this integration registers every entity it creates.
# Area discovery must never adopt our own entities: their names and device
# classes match the sensor keywords below (``lux``, ``illuminance``, ``motion``),
# so they would otherwise be fed back into the very inputs they mirror — and a
# ``state_changed`` of the LUX mirror re-triggers the tick it just ran,
# producing an endless log loop.
OWN_PLATFORM = "daynight_lighting"


def _is_own_entity(entity) -> bool:
    """True when *entity* was created by this integration."""
    return getattr(entity, "platform", None) == OWN_PLATFORM


def get_lights_in_area(hass: HomeAssistant, area_id: str, instance_name: str = "Area Discovery") -> list[str]:
    """Get all light entities in a specific area.

    Args:
        hass: Home Assistant instance
        area_id: The area ID to search
        instance_name: The instance name for logging

    Returns:
        List of light entity IDs in the area, sorted alphabetically
    """
    if not area_id or er is None or dr is None:
        return []

    try:
        entity_reg = er.async_get(hass)
        device_reg = dr.async_get(hass)
        if entity_reg is None or device_reg is None:
            return []
    except Exception:
        return []

    lights: list[str] = []

    for entity in entity_reg.entities.values():
        # Check if entity is in the target area
        entity_area_id = _get_entity_area_id(entity, entity_reg, device_reg)
        if entity_area_id != area_id:
            continue

        # Never adopt our own mirror entities (see _is_own_entity).
        if _is_own_entity(entity):
            continue

        # Check domain
        if not entity.entity_id.startswith("light."):
            continue

        # Skip virtual groups (Hue rooms/zones/groups, helper groups): they
        # are not lights and controlling them makes the instance fight itself.
        if _is_group_light(entity):
            _LOGGER.debug(
                "[%s] Area Discovery: skipping group entity '%s'",
                instance_name,
                entity.entity_id,
            )
            continue

        lights.append(entity.entity_id)

    lights.sort()
    _LOGGER.debug(
        "[%s] Area Discovery: Found %d lights in area '%s': %s",
        instance_name,
        len(lights),
        area_id,
        lights,
    )
    return lights


def get_motion_sensors_in_area(hass: HomeAssistant, area_id: str, instance_name: str = "Area Discovery") -> list[str]:
    """Get all motion and presence sensor entities in a specific area.

    Detects sensors by:
    1. device_class: motion (standard motion sensors)
    2. device_class: presence (presence sensors like mmWave)
    3. Entity ID containing motion/presence keywords (fallback)

    Args:
        hass: Home Assistant instance
        area_id: The area ID to search
        instance_name: The instance name for logging

    Returns:
        List of motion/presence sensor entity IDs in the area, sorted alphabetically
    """
    if not area_id or er is None or dr is None:
        return []

    try:
        entity_reg = er.async_get(hass)
        device_reg = dr.async_get(hass)
        if entity_reg is None or device_reg is None:
            return []
    except Exception:
        return []

    sensors: set[str] = set()

    for entity in entity_reg.entities.values():
        # Check if entity is in the target area
        entity_area_id = _get_entity_area_id(entity, entity_reg, device_reg)
        if entity_area_id != area_id:
            continue

        # Never adopt our own mirror entities (see _is_own_entity).
        if _is_own_entity(entity):
            continue

        # Check domain
        if not entity.entity_id.startswith("binary_sensor."):
            continue

        # Check device class from registry
        entity_device_class = getattr(
            entity, "original_device_class", None
        ) or getattr(entity, "device_class", None)

        if entity_device_class in ("motion", "presence"):
            sensors.add(entity.entity_id)
            continue

        # Fallback: check entity_id patterns
        if _is_motion_sensor_by_entity_id(entity.entity_id):
            sensors.add(entity.entity_id)

    result = sorted(sensors)
    _LOGGER.debug(
        "[%s] Area Discovery: Found %d motion sensors in area '%s': %s",
        instance_name,
        len(result),
        area_id,
        result,
    )
    return result


def get_illuminance_sensors_in_area(hass: HomeAssistant, area_id: str, instance_name: str = "Area Discovery") -> list[str]:
    """Get all illuminance sensor entities in a specific area.

    Detects sensors by:
    1. device_class: illuminance
    2. Entity ID containing illuminance/illumination/lux keywords (fallback)

    Args:
        hass: Home Assistant instance
        area_id: The area ID to search
        instance_name: The instance name for logging

    Returns:
        List of illuminance sensor entity IDs in the area, sorted alphabetically
    """
    if not area_id or er is None or dr is None:
        return []

    try:
        entity_reg = er.async_get(hass)
        device_reg = dr.async_get(hass)
        if entity_reg is None or device_reg is None:
            return []
    except Exception:
        return []

    sensors: set[str] = set()

    for entity in entity_reg.entities.values():
        # Check if entity is in the target area
        entity_area_id = _get_entity_area_id(entity, entity_reg, device_reg)
        if entity_area_id != area_id:
            continue

        # Never adopt our own mirror entities (see _is_own_entity).
        if _is_own_entity(entity):
            continue

        # Check domain
        if not entity.entity_id.startswith("sensor."):
            continue

        # Check device class from registry
        entity_device_class = getattr(
            entity, "original_device_class", None
        ) or getattr(entity, "device_class", None)

        if entity_device_class == "illuminance":
            sensors.add(entity.entity_id)
            continue

        # Fallback: check entity_id patterns
        if _is_illuminance_sensor_by_entity_id(entity.entity_id):
            sensors.add(entity.entity_id)

    result = sorted(sensors)
    _LOGGER.debug(
        "[%s] Area Discovery: Found %d illuminance sensors in area '%s': %s",
        instance_name,
        len(result),
        area_id,
        result,
    )
    return result


def get_area_name(hass: HomeAssistant, area_id: str) -> str | None:
    """Get the friendly name of an area.

    Args:
        hass: Home Assistant instance
        area_id: The area ID

    Returns:
        The area name, or None if not found
    """
    if not area_id or ar is None:
        return None

    try:
        area_reg = ar.async_get(hass)
        if area_reg is None:
            return None
        area = area_reg.async_get(area_id)
        return area.name if area else None
    except Exception:
        return None


def is_area_based(use_area_discovery: bool, area_id: str | None) -> bool:
    """Check if area-based discovery should be active.

    Args:
        use_area_discovery: Whether area discovery is enabled
        area_id: The configured area ID

    Returns:
        True if area discovery should be active
    """
    return use_area_discovery and area_id is not None
