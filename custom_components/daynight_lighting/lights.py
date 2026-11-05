"""Lights controller for DayNight Lighting.

Provides the configured lights list.  Night-session tracking (which lights
we turned on, etc.) has been moved to :class:`StateController` for
persistence.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

class LightsController:
    """The lights configured for one instance."""

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

