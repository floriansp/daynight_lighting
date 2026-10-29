"""Circadian colour temperature (sun elevation → Kelvin) for DayNight Lighting.

This module acts as an adapter between Home Assistant's sun entity
and the pure domain color calculation functions.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from .config import CircadianConfig
from .domain import calculate_kelvin_from_elevation
from .parsing import parse_sun_elevation

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


class CircadianController:
    """Computes colour temperature in Kelvin from sun elevation (circadian)."""

    def __init__(
        self,
        hass: HomeAssistant,
        config: CircadianConfig,
        instance_name: str,
    ) -> None:
        self._hass = hass
        self._config = config
        self._instance_name = instance_name

    def is_enabled(self) -> bool:
        """True if circadian colour is enabled in options."""
        return self._config.enabled

    def get_kelvin(self) -> tuple[int, float | None]:
        """Current circadian Kelvin and sun elevation. (min_kelvin, None) if sun unavailable or disabled."""
        # Get sun elevation from Home Assistant
        elevation = self._get_sun_elevation()

        # Delegate to pure domain function
        result = calculate_kelvin_from_elevation(
            elevation=elevation,
            min_kelvin=self._min_kelvin(),
            max_kelvin=self._max_kelvin(),
        )

        # Log for debugging
        if elevation is None:
            log_prefix = f"[{self._instance_name}] "
            _LOGGER.debug(
                "%sCircadian: sun unavailable, using min_kelvin=%s",
                log_prefix, result.kelvin,
            )

        return (result.kelvin, result.sun_elevation)

    def _get_sun_elevation(self) -> float | None:
        """Get sun elevation from Home Assistant sun entity.

        This is the adapter side - it reads from HA and provides
        the raw data for domain calculations.
        """
        if not self.is_enabled():
            return None

        sun = self._hass.states.get("sun.sun")
        elevation = parse_sun_elevation(sun)

        if elevation is None and sun is not None:
            _LOGGER.debug(
                "[%s] Circadian: invalid elevation %s",
                self._instance_name,
                sun.attributes.get("elevation"),
            )

        return elevation

    def get_expected_night_kelvin(self) -> int | None:
        """Current circadian Kelvin for night; None if circadian disabled."""
        if not self.is_enabled():
            return None
        kelvin, _ = self.get_kelvin()
        return kelvin

    def _min_kelvin(self) -> int:
        return self._config.min_kelvin

    def _max_kelvin(self) -> int:
        return self._config.max_kelvin
