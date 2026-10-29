"""Tests for pure parsing functions.

These tests verify the pure functions in parsing.py without any
Home Assistant dependencies or side effects.
"""

from __future__ import annotations

from unittest.mock import MagicMock


from custom_components.daynight_lighting.parsing import (
    calculate_compensated_lux,
    get_weather_modifier,
    is_motion_state_on,
    parse_lux_state,
    parse_sun_elevation,
    parse_weather_condition,
)


class TestParseLuxState:
    """Tests for parse_lux_state function."""

    def test_valid_numeric_state(self):
        """Valid numeric state is parsed correctly."""
        state = MagicMock()
        state.state = "150.5"
        assert parse_lux_state(state) == 150.5

    def test_integer_state(self):
        """Integer state is parsed as float."""
        state = MagicMock()
        state.state = "200"
        assert parse_lux_state(state) == 200.0

    def test_zero_lux(self):
        """Zero LUX is parsed correctly."""
        state = MagicMock()
        state.state = "0"
        assert parse_lux_state(state) == 0.0

    def test_negative_lux(self):
        """Negative LUX is parsed (though typically invalid in practice)."""
        state = MagicMock()
        state.state = "-10"
        assert parse_lux_state(state) == -10.0

    def test_none_state(self):
        """None state returns None."""
        assert parse_lux_state(None) is None

    def test_unknown_state(self):
        """'unknown' state returns None."""
        state = MagicMock()
        state.state = "unknown"
        assert parse_lux_state(state) is None

    def test_unavailable_state(self):
        """'unavailable' state returns None."""
        state = MagicMock()
        state.state = "unavailable"
        assert parse_lux_state(state) is None

    def test_none_string_state(self):
        """None string state returns None."""
        state = MagicMock()
        state.state = None
        assert parse_lux_state(state) is None

    def test_non_numeric_state(self):
        """Non-numeric state returns None."""
        state = MagicMock()
        state.state = "error"
        assert parse_lux_state(state) is None

    def test_float_with_decimal(self):
        """Float with decimal point parsed correctly."""
        state = MagicMock()
        state.state = "1234.567"
        assert parse_lux_state(state) == 1234.567

    def test_scientific_notation(self):
        """Scientific notation parsed correctly."""
        state = MagicMock()
        state.state = "1.5e3"
        assert parse_lux_state(state) == 1500.0


class TestParseWeatherCondition:
    """Tests for parse_weather_condition function."""

    def test_sunny_condition(self):
        """Sunny condition parsed and lowercased."""
        state = MagicMock()
        state.state = "Sunny"
        assert parse_weather_condition(state) == "sunny"

    def test_cloudy_condition(self):
        """Cloudy condition parsed and lowercased."""
        state = MagicMock()
        state.state = "Cloudy"
        assert parse_weather_condition(state) == "cloudy"

    def test_rainy_condition(self):
        """Rainy condition parsed and lowercased."""
        state = MagicMock()
        state.state = "Rainy"
        assert parse_weather_condition(state) == "rainy"

    def test_already_lowercase(self):
        """Already lowercase condition stays lowercase."""
        state = MagicMock()
        state.state = "partlycloudy"
        assert parse_weather_condition(state) == "partlycloudy"

    def test_mixed_case(self):
        """Mixed case is normalized to lowercase."""
        state = MagicMock()
        state.state = "PartlyCloudy"
        assert parse_weather_condition(state) == "partlycloudy"

    def test_none_state(self):
        """None state returns None."""
        assert parse_weather_condition(None) is None

    def test_unknown_state(self):
        """'unknown' state returns None."""
        state = MagicMock()
        state.state = "unknown"
        assert parse_weather_condition(state) is None

    def test_unavailable_state(self):
        """'unavailable' state returns None."""
        state = MagicMock()
        state.state = "unavailable"
        assert parse_weather_condition(state) is None

    def test_none_string_state(self):
        """None string state returns None."""
        state = MagicMock()
        state.state = None
        assert parse_weather_condition(state) is None


class TestParseSunElevation:
    """Tests for parse_sun_elevation function."""

    def test_positive_elevation(self):
        """Positive elevation parsed correctly."""
        state = MagicMock()
        state.attributes = {"elevation": 45.5}
        assert parse_sun_elevation(state) == 45.5

    def test_negative_elevation(self):
        """Negative elevation (below horizon) parsed correctly."""
        state = MagicMock()
        state.attributes = {"elevation": -10.5}
        assert parse_sun_elevation(state) == -10.5

    def test_zero_elevation(self):
        """Zero elevation (horizon) parsed correctly."""
        state = MagicMock()
        state.attributes = {"elevation": 0.0}
        assert parse_sun_elevation(state) == 0.0

    def test_integer_elevation(self):
        """Integer elevation parsed as float."""
        state = MagicMock()
        state.attributes = {"elevation": 30}
        assert parse_sun_elevation(state) == 30.0

    def test_none_state(self):
        """None state returns None."""
        assert parse_sun_elevation(None) is None

    def test_no_attributes(self):
        """State without attributes returns None."""
        state = MagicMock(spec=[])  # No attributes attribute
        assert parse_sun_elevation(state) is None

    def test_missing_elevation_attribute(self):
        """State without elevation attribute returns None."""
        state = MagicMock()
        state.attributes = {"next_rising": "2024-01-01"}
        assert parse_sun_elevation(state) is None

    def test_none_elevation(self):
        """None elevation returns None."""
        state = MagicMock()
        state.attributes = {"elevation": None}
        assert parse_sun_elevation(state) is None

    def test_non_numeric_elevation(self):
        """Non-numeric elevation returns None."""
        state = MagicMock()
        state.attributes = {"elevation": "invalid"}
        assert parse_sun_elevation(state) is None

    def test_empty_attributes(self):
        """Empty attributes dict returns None."""
        state = MagicMock()
        state.attributes = {}
        assert parse_sun_elevation(state) is None


class TestIsMotionStateOn:
    """Tests for is_motion_state_on function."""

    def test_state_on(self):
        """State 'on' returns True."""
        state = MagicMock()
        state.state = "on"
        assert is_motion_state_on(state) is True

    def test_state_off(self):
        """State 'off' returns False."""
        state = MagicMock()
        state.state = "off"
        assert is_motion_state_on(state) is False

    def test_none_state(self):
        """None state returns False."""
        assert is_motion_state_on(None) is False

    def test_unknown_state(self):
        """'unknown' state returns False."""
        state = MagicMock()
        state.state = "unknown"
        assert is_motion_state_on(state) is False

    def test_unavailable_state(self):
        """'unavailable' state returns False."""
        state = MagicMock()
        state.state = "unavailable"
        assert is_motion_state_on(state) is False

    def test_case_sensitive(self):
        """State check is case-sensitive."""
        state = MagicMock()
        state.state = "ON"
        assert is_motion_state_on(state) is False

        state.state = "On"
        assert is_motion_state_on(state) is False


class TestCalculateCompensatedLux:
    """Tests for calculate_compensated_lux function."""

    def test_no_calibration(self):
        """No calibration returns measured value unchanged."""
        result = calculate_compensated_lux(100.0, None, 50)
        assert result == 100.0

    def test_no_brightness(self):
        """No brightness returns measured value unchanged."""
        result = calculate_compensated_lux(100.0, 40.0, None)
        assert result == 100.0

    def test_full_compensation(self):
        """Full compensation at 100% brightness."""
        # measured=100, calibration=40, brightness=100
        # lamp_contrib = 40 * 1.0 = 40
        # ambient = 100 - 40 = 60
        result = calculate_compensated_lux(100.0, 40.0, 100)
        assert result == 60.0

    def test_half_compensation(self):
        """Half compensation at 50% brightness."""
        # measured=100, calibration=40, brightness=50
        # lamp_contrib = 40 * 0.5 = 20
        # ambient = 100 - 20 = 80
        result = calculate_compensated_lux(100.0, 40.0, 50)
        assert result == 80.0

    def test_zero_brightness(self):
        """Zero brightness returns measured value (no lamp contribution)."""
        # lamp_contrib = 40 * 0 = 0
        result = calculate_compensated_lux(100.0, 40.0, 0)
        assert result == 100.0

    def test_clamped_to_zero(self):
        """Result is clamped to minimum of 0."""
        # measured=10, calibration=40, brightness=100
        # lamp_contrib = 40, ambient would be -30
        result = calculate_compensated_lux(10.0, 40.0, 100)
        assert result == 0.0

    def test_large_compensation(self):
        """Large calibration value works correctly."""
        result = calculate_compensated_lux(500.0, 200.0, 75)
        # lamp_contrib = 200 * 0.75 = 150
        # ambient = 500 - 150 = 350
        assert result == 350.0

    def test_fractional_result(self):
        """Fractional results are preserved."""
        result = calculate_compensated_lux(100.0, 33.0, 50)
        # lamp_contrib = 33 * 0.5 = 16.5
        # ambient = 100 - 16.5 = 83.5
        assert result == 83.5


class TestGetWeatherModifier:
    """Tests for get_weather_modifier function."""

    def test_sunny_modifier(self):
        """Sunny condition returns configured modifier."""
        modifiers = {"sunny": 0.8, "cloudy": 1.2}
        assert get_weather_modifier("sunny", modifiers) == 0.8

    def test_cloudy_modifier(self):
        """Cloudy condition returns configured modifier."""
        modifiers = {"sunny": 0.8, "cloudy": 1.2}
        assert get_weather_modifier("cloudy", modifiers) == 1.2

    def test_unknown_condition_default(self):
        """Unknown condition returns default."""
        modifiers = {"sunny": 0.8}
        assert get_weather_modifier("unknown", modifiers) == 1.0

    def test_none_condition_default(self):
        """None condition returns default."""
        modifiers = {"sunny": 0.8}
        assert get_weather_modifier(None, modifiers) == 1.0

    def test_empty_modifiers(self):
        """Empty modifiers dict returns default."""
        assert get_weather_modifier("sunny", {}) == 1.0

    def test_clamped_to_max(self):
        """Modifier clamped to max_modifier."""
        modifiers = {"sunny": 2.0}
        assert get_weather_modifier("sunny", modifiers) == 1.5

    def test_clamped_to_min(self):
        """Modifier clamped to min_modifier."""
        modifiers = {"sunny": 0.1}
        assert get_weather_modifier("sunny", modifiers) == 0.5

    def test_custom_default(self):
        """Custom default is used."""
        modifiers = {}
        assert get_weather_modifier("sunny", modifiers, default=0.9) == 0.9

    def test_custom_range(self):
        """Custom min/max range is respected."""
        modifiers = {"sunny": 0.1}
        assert get_weather_modifier("sunny", modifiers, min_modifier=0.0, max_modifier=2.0) == 0.1

    def test_custom_range_clamping(self):
        """Custom range clamping works."""
        modifiers = {"sunny": 3.0}
        assert get_weather_modifier("sunny", modifiers, max_modifier=2.0) == 2.0

    def test_rainy_condition(self):
        """Rainy condition with high modifier."""
        modifiers = {"rainy": 1.4, "snowy": 1.5}
        assert get_weather_modifier("rainy", modifiers) == 1.4

    def test_case_sensitive(self):
        """Condition lookup is case-sensitive."""
        modifiers = {"sunny": 0.8}
        assert get_weather_modifier("Sunny", modifiers) == 1.0  # Not found
