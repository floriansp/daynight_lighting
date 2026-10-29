"""Weather condition reader for DayNight Lighting brightness adjustment."""

from __future__ import annotations

import logging

from homeassistant.core import HomeAssistant

from .config import WeatherConfig
from .parsing import get_weather_modifier, parse_weather_condition

_LOGGER = logging.getLogger(__name__)


class WeatherReader:
    """Read weather entity and provide brightness modifiers for day mode."""

    def __init__(
        self,
        hass: HomeAssistant,
        config: WeatherConfig,
        instance_name: str,
    ) -> None:
        self._hass = hass
        self._config = config
        self._instance_name = instance_name

    def is_enabled(self) -> bool:
        """True if weather brightness adjustment is enabled."""
        return self._config.enabled

    def get_weather_entity(self) -> str | None:
        """Weather entity_id from config."""
        return self._config.entity

    def get_current_condition(self) -> str | None:
        """Current weather condition (sunny, cloudy, rainy, etc.).

        Returns None if entity unavailable or state invalid.
        """
        entity_id = self.get_weather_entity()
        if not entity_id:
            _LOGGER.debug(
                "[%s] No weather entity configured",
                self._instance_name,
            )
            return None

        state = self._hass.states.get(entity_id)
        condition = parse_weather_condition(state)

        if condition is None and state is not None:
            _LOGGER.debug(
                "[%s] Weather entity %s unavailable: %s",
                self._instance_name,
                entity_id,
                state.state,
            )

        return condition

    def get_brightness_modifier(self) -> float:
        """Brightness multiplier based on current weather condition.

        Returns:
            float: Multiplier in range 0.5-1.5 (default 1.0 if unavailable).
        """
        if not self.is_enabled():
            return 1.0

        condition = self.get_current_condition()
        if condition is None:
            return 1.0

        # Get configured modifiers
        modifiers = self._config.brightness_modifiers

        # Use pure function to get modifier
        modifier = get_weather_modifier(condition, modifiers)

        _LOGGER.debug(
            "[%s] Weather: condition=%s, modifier=%.2fx",
            self._instance_name,
            condition,
            modifier,
        )

        return modifier
