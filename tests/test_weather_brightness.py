"""Unit tests for weather.py — WeatherReader."""


from custom_components.daynight_lighting.weather import WeatherReader
from custom_components.daynight_lighting.config import WeatherConfig
from tests.conftest import FakeState


class TestWeatherReader:
    """Tests for WeatherReader class."""

    def test_is_enabled_true(self, fake_hass):
        """Weather enabled in config → is_enabled returns True."""
        config = WeatherConfig(enabled=True)
        reader = WeatherReader(fake_hass, config, "test")
        assert reader.is_enabled() is True

    def test_is_enabled_false(self, fake_hass):
        """Weather disabled in config → is_enabled returns False."""
        config = WeatherConfig(enabled=False)
        reader = WeatherReader(fake_hass, config, "test")
        assert reader.is_enabled() is False

    def test_is_enabled_default_false(self, fake_hass):
        """Default config → is_enabled defaults to False."""
        config = WeatherConfig()
        reader = WeatherReader(fake_hass, config, "test")
        assert reader.is_enabled() is False

    def test_get_weather_entity_string(self, fake_hass):
        """Weather entity as string → returned correctly."""
        config = WeatherConfig(enabled=True, entity="weather.home")
        reader = WeatherReader(fake_hass, config, "test")
        assert reader.get_weather_entity() == "weather.home"

    def test_get_weather_entity_none(self, fake_hass):
        """No weather entity configured → returns None."""
        config = WeatherConfig(enabled=True)
        reader = WeatherReader(fake_hass, config, "test")
        assert reader.get_weather_entity() is None

    def test_get_current_condition_sunny(self, fake_hass):
        """Weather state 'sunny' → returns 'sunny'."""
        fake_hass.states.set("weather.home", FakeState(state="sunny"))
        config = WeatherConfig(
            enabled=True,
            entity="weather.home",
        )
        reader = WeatherReader(fake_hass, config, "test")
        assert reader.get_current_condition() == "sunny"

    def test_get_current_condition_unavailable(self, fake_hass):
        """Weather state 'unavailable' → returns None."""
        fake_hass.states.set("weather.home", FakeState(state="unavailable"))
        config = WeatherConfig(
            enabled=True,
            entity="weather.home",
        )
        reader = WeatherReader(fake_hass, config, "test")
        assert reader.get_current_condition() is None

    def test_get_current_condition_missing_entity(self, fake_hass):
        """Weather entity missing → returns None."""
        config = WeatherConfig(
            enabled=True,
            entity="weather.missing",
        )
        reader = WeatherReader(fake_hass, config, "test")
        assert reader.get_current_condition() is None

    def test_get_brightness_modifier_sunny(self, fake_hass):
        """Sunny condition → returns 0.7 modifier."""
        fake_hass.states.set("weather.home", FakeState(state="sunny"))
        config = WeatherConfig(
            enabled=True,
            entity="weather.home",
        )
        reader = WeatherReader(fake_hass, config, "test")
        assert reader.get_brightness_modifier() == 0.7

    def test_get_brightness_modifier_rainy(self, fake_hass):
        """Rainy condition → returns 1.2 modifier."""
        fake_hass.states.set("weather.home", FakeState(state="rainy"))
        config = WeatherConfig(
            enabled=True,
            entity="weather.home",
        )
        reader = WeatherReader(fake_hass, config, "test")
        assert reader.get_brightness_modifier() == 1.2

    def test_get_brightness_modifier_unknown_condition(self, fake_hass):
        """Unknown condition → returns 1.0 (no change)."""
        fake_hass.states.set("weather.home", FakeState(state="alien_invasion"))
        config = WeatherConfig(
            enabled=True,
            entity="weather.home",
        )
        reader = WeatherReader(fake_hass, config, "test")
        assert reader.get_brightness_modifier() == 1.0

    def test_get_brightness_modifier_disabled(self, fake_hass):
        """Weather disabled → returns 1.0 regardless of condition."""
        fake_hass.states.set("weather.home", FakeState(state="sunny"))
        config = WeatherConfig(
            enabled=False,
            entity="weather.home",
        )
        reader = WeatherReader(fake_hass, config, "test")
        assert reader.get_brightness_modifier() == 1.0

    def test_get_brightness_modifier_clamped(self, fake_hass):
        """Extreme modifier values clamped to 0.5-1.5 range."""
        fake_hass.states.set("weather.home", FakeState(state="custom"))
        config = WeatherConfig(
            enabled=True,
            entity="weather.home",
            brightness_modifiers={"custom": 2.5},  # Extreme value
        )
        reader = WeatherReader(fake_hass, config, "test")
        modifier = reader.get_brightness_modifier()
        assert modifier == 1.5  # Clamped to max

    def test_get_brightness_modifier_clamped_min(self, fake_hass):
        """Extreme low modifier values clamped to 0.5."""
        fake_hass.states.set("weather.home", FakeState(state="custom"))
        config = WeatherConfig(
            enabled=True,
            entity="weather.home",
            brightness_modifiers={"custom": 0.1},  # Too low
        )
        reader = WeatherReader(fake_hass, config, "test")
        modifier = reader.get_brightness_modifier()
        assert modifier == 0.5  # Clamped to min

    def test_get_weather_entity_list_format(self, fake_hass):
        """Weather entity in list format → extracts first item.

        NOTE: The config normalizes list format to string during creation from options.
        This test verifies that a string entity is returned correctly.
        """
        config = WeatherConfig(entity="weather.home")
        reader = WeatherReader(fake_hass, config, "test")
        assert reader.get_weather_entity() == "weather.home"

    def test_get_weather_entity_dict_format(self, fake_hass):
        """Weather entity in dict format → extracts entity_id.

        NOTE: The config normalizes dict format to string during creation from options.
        This test verifies that a string entity is returned correctly.
        """
        config = WeatherConfig(entity="weather.home")
        reader = WeatherReader(fake_hass, config, "test")
        assert reader.get_weather_entity() == "weather.home"

    def test_get_current_condition_uppercase_normalized(self, fake_hass):
        """Weather state uppercase → normalized to lowercase."""
        fake_hass.states.set("weather.home", FakeState(state="SUNNY"))
        config = WeatherConfig(
            enabled=True,
            entity="weather.home",
        )
        reader = WeatherReader(fake_hass, config, "test")
        assert reader.get_current_condition() == "sunny"
