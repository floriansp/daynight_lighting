"""What area discovery means for one instance.

An area-based instance adopts the lights and sensors it finds in its area.
This module owns that picture: the cached registry scan, which sensors are in
effect (discovered, minus the excluded ones, plus the one set by hand), and a
snapshot of what was adopted so a registry event can tell whether anything
that matters changed.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from .config import DayNightConfig

__all__ = ["DISCOVERY_TTL_SECONDS", "InstanceDiscovery"]

_LOGGER = logging.getLogger(__name__)

# Safety-net re-scan interval. Primary invalidation is event-driven: the
# entity/device/area registries are listened to and drop the cache the moment
# something changes. This TTL only re-syncs after a few minutes in case a
# registry event is ever missed, so a newly added lamp or sensor is never
# silently ignored for long — but we no longer re-scan every minute.
DISCOVERY_TTL_SECONDS = 300


class InstanceDiscovery:
    """Cached area discovery and sensor resolution of one instance."""

    def __init__(
        self,
        hass: HomeAssistant,
        get_config: Callable[[], DayNightConfig],
        instance_name: str = "",
    ) -> None:
        """Initialize the discovery.

        Args:
            hass: Home Assistant instance
            get_config: Resolves the current config; options can change, so
                the discovery never keeps one
            instance_name: Instance name for logging
        """
        self._hass = hass
        self._get_config = get_config
        self._instance_name = instance_name
        # (monotonic timestamp, scan result)
        self._cache: tuple[float, dict[str, Any]] | None = None
        # Entity set adopted at the last (re)start of the listeners.
        self._adopted: tuple | None = None

    def is_area_based(self) -> bool:
        """True when this instance adopts what it finds in its area."""
        cfg = self._get_config()
        return bool(cfg.is_area_based() and cfg.area_id)

    def scan(self) -> dict[str, Any]:
        """Area discovery, cached so the registries are scanned rarely.

        Both the entity attributes and the sensor resolution read from here,
        so the area registries are not re-scanned (and their DEBUG lines not
        re-logged) on every state read or sensor event. The cache is dropped
        on every options change and on every registry update; the TTL is only
        a safety net for a missed event.
        """
        cfg = self._get_config()
        if not (cfg.is_area_based() and cfg.area_id):
            return {}

        now = time.monotonic()
        if self._cache is not None and now - self._cache[0] < DISCOVERY_TTL_SECONDS:
            return self._cache[1]

        from .area_discovery import (
            get_area_name,
            get_illuminance_sensors_in_area,
            get_lights_in_area,
            get_motion_sensors_in_area,
        )

        result = {
            "area_name": get_area_name(self._hass, cfg.area_id) or cfg.area_id,
            "lights_in_area": get_lights_in_area(
                self._hass, cfg.area_id, self._instance_name
            ),
            "motion_sensors": get_motion_sensors_in_area(
                self._hass, cfg.area_id, self._instance_name
            ),
            "illuminance_sensors": get_illuminance_sensors_in_area(
                self._hass, cfg.area_id, self._instance_name
            ),
        }
        self._cache = (now, result)
        return result

    def invalidate(self) -> None:
        """Drop the cached scan, so the next read scans the registries."""
        self._cache = None

    def resolve_sensor_ids(self, kind: str) -> list[str]:
        """Sensors of *kind* ("light_sensor" or "motion_sensor") in effect.

        With area discovery the sensors found in the area are used, plus the
        one configured by hand unless discovery already found it. Without it
        only the configured sensor counts.
        """
        cfg = self._get_config()
        manual = getattr(cfg, kind)
        if not (cfg.is_area_based() and cfg.area_id):
            if manual:
                return [manual] if isinstance(manual, str) else list(manual)
            return []

        discovery = self.scan()
        sensor_ids = list(
            discovery["motion_sensors"]
            if kind == "motion_sensor"
            else discovery["illuminance_sensors"]
        )
        # Motion sensors the user opted out of (e.g. a camera AI-detection
        # sensor that latches on) are dropped from the discovered set. The
        # explicitly configured manual sensor below is still honoured.
        if kind == "motion_sensor" and cfg.excluded_motion_sensors:
            excluded_lower = {s.lower() for s in cfg.excluded_motion_sensors}
            kept = [s for s in sensor_ids if s.lower() not in excluded_lower]
            if len(kept) != len(sensor_ids):
                _LOGGER.debug(
                    "[%s] Area discovery: excluded %d motion sensor(s)",
                    self._instance_name,
                    len(sensor_ids) - len(kept),
                )
            sensor_ids = kept
        if manual:
            manual_list = [manual] if isinstance(manual, str) else list(manual)
            existing_lower = {s.lower() for s in sensor_ids}
            for manual_sensor in manual_list:
                if manual_sensor.lower() not in existing_lower:
                    sensor_ids.append(manual_sensor)
                    existing_lower.add(manual_sensor.lower())
                    _LOGGER.debug(
                        "[%s] Area discovery: Added manual %s %s to discovered sensors",
                        self._instance_name,
                        kind,
                        manual_sensor,
                    )
                else:
                    _LOGGER.debug(
                        "[%s] Area discovery: Manual %s %s already in discovered sensors, skipping",
                        self._instance_name,
                        kind,
                        manual_sensor,
                    )
        return sensor_ids

    def snapshot(self) -> tuple:
        """The entities this instance adopts via area discovery.

        A tuple of sorted tuples ``(lights, motion_sensors,
        illuminance_sensors)`` so a registry change is detected by inequality.
        Empty tuple when the instance is not area-based. The lights reflect
        what is *controlled*: the explicitly included lights, or — when none
        are included — every discovered area light.
        """
        cfg = self._get_config()
        if not (cfg.is_area_based() and cfg.area_id):
            return ()
        discovery = self.scan()
        if cfg.included_lights:
            lights = tuple(sorted(cfg.included_lights))
        else:
            lights = tuple(sorted(discovery["lights_in_area"]))
        return (
            lights,
            tuple(sorted(discovery["motion_sensors"])),
            tuple(sorted(discovery["illuminance_sensors"])),
        )

    def remember_adopted(self) -> None:
        """Record what is adopted now, as the baseline for later changes."""
        self._adopted = self.snapshot()

    def forget_adopted(self) -> None:
        """Drop the baseline, e.g. because the options changed."""
        self._adopted = None

    def adoption_changed(self) -> bool:
        """Re-scan and say whether the adopted entities differ from the baseline."""
        self.invalidate()
        return self.snapshot() != self._adopted
