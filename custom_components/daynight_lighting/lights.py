"""Lights controller for DayNight Lighting.

Provides the configured lights list, state queries, and snapshot
functionality.  Night-session tracking (which lights we turned on, etc.)
has been moved to :class:`StateController` for persistence.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from homeassistant.const import STATE_ON

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

# Snapshot: entity_id -> (state, brightness 0-255, color_temp mired)
LightsSnapshot = dict[str, tuple[str, int | None, int | None]]


class LightsController:
    """Light list from config, state queries, and snapshots."""

    def __init__(
        self,
        hass: HomeAssistant,
        lights: list[str],
        instance_name: str,
    ) -> None:
        self._hass = hass
        self._lights = lights
        self._instance_name = instance_name

    def get_lights_list(self) -> list[str]:
        """Configured light entity_ids."""
        return list(self._lights)

    def get_lights_that_are_off(self, lights: list[str]) -> list[str]:
        """Subset of *lights* that are currently off (or unknown)."""
        return [
            lid
            for lid in lights
            if (s := self._hass.states.get(lid)) is None
            or s.state != STATE_ON
        ]

    def snapshot_lights(self, lights: list[str]) -> LightsSnapshot:
        """Current state of lights.

        Returns ``entity_id -> (state, brightness 0-255, color_temp mired)``.
        """
        out: LightsSnapshot = {}
        for lid in lights:
            s = self._hass.states.get(lid)
            if s is None:
                out[lid] = ("unknown", None, None)
            else:
                attrs = getattr(s, "attributes", {}) or {}
                br = attrs.get("brightness")
                ct = attrs.get("color_temp")
                if ct is not None:
                    try:
                        ct = int(ct)
                    except (TypeError, ValueError):
                        ct = None
                out[lid] = (s.state, br, ct)
        return out
