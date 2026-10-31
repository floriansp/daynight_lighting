"""Pure domain tests for data models.

These tests verify the data structures in domain/models.py
without any Home Assistant dependencies or side effects.
"""

from __future__ import annotations

import pytest

from custom_components.daynight_lighting.domain.models import (
    Mode,
    CircadianResult,
)


class TestModeEnum:
    """Tests for Mode enumeration."""

    def test_enum_values(self):
        """Mode enum has correct string values."""
        assert Mode.DAY.value == "day"
        assert Mode.NIGHT.value == "night"
        assert Mode.SLEEP.value == "sleep"
        assert Mode.WAKEUP.value == "wakeup"

    def test_enum_equality(self):
        """Mode enum members compare correctly."""
        assert Mode.DAY == Mode.DAY
        assert Mode.DAY != Mode.NIGHT
        assert Mode("day") == Mode.DAY
        assert Mode("night") == Mode.NIGHT

    def test_from_string(self):
        """Mode can be created from string values."""
        assert Mode("day") is Mode.DAY
        assert Mode("night") is Mode.NIGHT
        assert Mode("sleep") is Mode.SLEEP
        assert Mode("wakeup") is Mode.WAKEUP

    def test_invalid_string_raises(self):
        """Invalid string raises ValueError."""
        with pytest.raises(ValueError):
            Mode("invalid")

    def test_iteration(self):
        """Mode enum can be iterated."""
        modes = list(Mode)
        assert len(modes) == 4
        assert set(modes) == {Mode.DAY, Mode.NIGHT, Mode.SLEEP, Mode.WAKEUP}

    def test_string_conversion(self):
        """String representation works."""
        assert str(Mode.DAY) == "Mode.DAY"
        assert repr(Mode.DAY) == "<Mode.DAY: 'day'>"


class TestCircadianResult:
    """Tests for CircadianResult dataclass."""

    def test_creation_with_minimal_fields(self):
        """CircadianResult can be created with only required fields."""
        result = CircadianResult(
            kelvin=4000,
        )

        assert result.kelvin == 4000
        assert result.sun_elevation is None
        assert result.source == "circadian"  # Default value

    def test_creation_with_all_fields(self):
        """CircadianResult can be created with all optional fields."""
        result = CircadianResult(
            kelvin=4500,
            sun_elevation=30.5,
            source="max_fallback",
        )

        assert result.kelvin == 4500
        assert result.sun_elevation == 30.5
        assert result.source == "max_fallback"

    def test_default_source(self):
        """CircadianResult has default source value."""
        result = CircadianResult(kelvin=4000)
        assert result.source == "circadian"

    def test_valid_source_values(self):
        """CircadianResult accepts various source values."""
        sources = ["circadian", "min_fallback", "max_fallback", "custom"]

        for source in sources:
            result = CircadianResult(kelvin=4000, source=source)
            assert result.source == source

    def test_immutability(self):
        """CircadianResult should be immutable (frozen dataclass)."""
        result = CircadianResult(kelvin=4000)

        with pytest.raises(Exception):
            result.kelvin = 4500  # Should raise

    def test_equality(self):
        """CircadianResult equality works correctly."""
        result1 = CircadianResult(4000, 30.0, "circadian")
        result2 = CircadianResult(4000, 30.0, "circadian")
        result3 = CircadianResult(4500, 30.0, "circadian")
        result4 = CircadianResult(4000, 40.0, "circadian")
        result5 = CircadianResult(4000, 30.0, "min_fallback")

        assert result1 == result2
        assert result1 != result3
        assert result1 != result4
        assert result1 != result5

    def test_hashability(self):
        """CircadianResult is hashable (can be used in sets/dicts)."""
        result1 = CircadianResult(4000, 30.0, "circadian")
        result2 = CircadianResult(4000, 30.0, "circadian")
        result3 = CircadianResult(4500, 40.0, "min_fallback")

        set_of_results = {result1, result2, result3}
        assert len(set_of_results) == 2  # result1 and result2 are equal
        assert result1 in set_of_results
        assert result3 in set_of_results

    def test_repr(self):
        """String representation is informative."""
        result = CircadianResult(4500, 25.5, "circadian")
        repr_str = repr(result)

        assert "CircadianResult" in repr_str
        assert "4500" in repr_str
        assert "25.5" in repr_str
        assert "circadian" in repr_str
