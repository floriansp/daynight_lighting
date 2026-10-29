"""Tests for CircadianController — kelvin calculation from sun elevation.

Tests is_enabled(), get_kelvin(), and get_expected_night_kelvin().
"""

from __future__ import annotations



from custom_components.daynight_lighting.circadian import CircadianController
from custom_components.daynight_lighting.config import CircadianConfig

from tests.conftest import FakeState


def _make_config(
    enabled: bool = True,
    min_kelvin: int = 2700,
    max_kelvin: int = 5500,
) -> CircadianConfig:
    """Create a CircadianConfig."""
    return CircadianConfig(
        enabled=enabled,
        min_kelvin=min_kelvin,
        max_kelvin=max_kelvin,
    )


def _make_controller(
    fake_hass,
    enabled: bool = True,
    min_kelvin: int = 2700,
    max_kelvin: int = 5500,
) -> CircadianController:
    """Create a CircadianController."""
    config = _make_config(enabled=enabled, min_kelvin=min_kelvin, max_kelvin=max_kelvin)
    return CircadianController(
        hass=fake_hass,
        config=config,
        instance_name="Test",
    )


# ===================================================================
#  is_enabled
# ===================================================================


class TestIsEnabled:
    """Tests for is_enabled method."""

    def test_enabled_when_config_true(self, fake_hass):
        """Returns True when enabled in config."""
        controller = _make_controller(fake_hass, enabled=True)
        assert controller.is_enabled() is True

    def test_disabled_when_config_false(self, fake_hass):
        """Returns False when disabled in config."""
        controller = _make_controller(fake_hass, enabled=False)
        assert controller.is_enabled() is False


# ===================================================================
#  get_kelvin
# ===================================================================


class TestGetKelvin:
    """Tests for get_kelvin method."""

    def test_returns_min_kelvin_when_disabled(self, fake_hass):
        """When disabled, returns min_kelvin with None elevation."""
        controller = _make_controller(fake_hass, enabled=False, min_kelvin=2700)
        kelvin, elevation = controller.get_kelvin()

        assert kelvin == 2700
        assert elevation is None

    def test_returns_min_kelvin_when_no_sun_entity(self, fake_hass):
        """When sun.sun missing, returns min_kelvin."""
        controller = _make_controller(fake_hass, enabled=True, min_kelvin=2700)
        # Don't set sun.sun state
        kelvin, elevation = controller.get_kelvin()

        assert kelvin == 2700
        assert elevation is None

    def test_returns_min_kelvin_when_no_elevation_attribute(self, fake_hass):
        """When sun.sun has no elevation attribute, returns min_kelvin."""
        fake_hass.states.set("sun.sun", FakeState(state="above_horizon", attributes={}))
        controller = _make_controller(fake_hass, enabled=True, min_kelvin=2700)
        kelvin, elevation = controller.get_kelvin()

        assert kelvin == 2700
        assert elevation is None

    def test_calculates_kelvin_from_high_elevation(self, fake_hass):
        """High sun elevation gives warmer (higher) kelvin."""
        fake_hass.states.set(
            "sun.sun",
            FakeState(state="above_horizon", attributes={"elevation": 45.0}),
        )
        controller = _make_controller(fake_hass, enabled=True, min_kelvin=2700, max_kelvin=5500)
        kelvin, elevation = controller.get_kelvin()

        assert elevation == 45.0
        assert kelvin > 2700  # Warmer than min
        assert kelvin <= 5500  # At or below max

    def test_calculates_kelvin_from_low_elevation(self, fake_hass):
        """Low sun elevation gives cooler (lower) kelvin."""
        fake_hass.states.set(
            "sun.sun",
            FakeState(state="above_horizon", attributes={"elevation": 5.0}),
        )
        controller = _make_controller(fake_hass, enabled=True, min_kelvin=2700, max_kelvin=5500)
        kelvin, elevation = controller.get_kelvin()

        assert elevation == 5.0
        assert kelvin >= 2700  # At or above min
        assert kelvin < 5500  # Cooler than max

    def test_returns_max_kelvin_at_max_elevation(self, fake_hass):
        """Maximum elevation gives max_kelvin."""
        fake_hass.states.set(
            "sun.sun",
            FakeState(state="above_horizon", attributes={"elevation": 90.0}),
        )
        controller = _make_controller(fake_hass, enabled=True, min_kelvin=2700, max_kelvin=5500)
        kelvin, elevation = controller.get_kelvin()

        assert elevation == 90.0
        assert kelvin == 5500  # Max kelvin

    def test_returns_low_kelvin_at_night(self, fake_hass):
        """Negative elevation (night) gives low kelvin (but not necessarily min)."""
        fake_hass.states.set(
            "sun.sun",
            FakeState(state="below_horizon", attributes={"elevation": -10.0}),
        )
        controller = _make_controller(fake_hass, enabled=True, min_kelvin=2700, max_kelvin=5500)
        kelvin, elevation = controller.get_kelvin()

        assert elevation == -10.0
        assert kelvin >= 2700  # At or above min (domain may have different min threshold)

    def test_handles_string_elevation(self, fake_hass):
        """Handles string elevation values."""
        fake_hass.states.set(
            "sun.sun",
            FakeState(state="above_horizon", attributes={"elevation": "30.5"}),
        )
        controller = _make_controller(fake_hass, enabled=True, min_kelvin=2700, max_kelvin=5500)
        kelvin, elevation = controller.get_kelvin()

        assert elevation == 30.5
        assert kelvin > 2700

    def test_handles_invalid_elevation(self, fake_hass):
        """Handles invalid elevation values gracefully."""
        fake_hass.states.set(
            "sun.sun",
            FakeState(state="above_horizon", attributes={"elevation": "invalid"}),
        )
        controller = _make_controller(fake_hass, enabled=True, min_kelvin=2700)
        kelvin, elevation = controller.get_kelvin()

        assert elevation is None
        assert kelvin == 2700  # Min kelvin


# ===================================================================
#  get_expected_night_kelvin
# ===================================================================


class TestGetExpectedNightKelvin:
    """Tests for get_expected_night_kelvin method."""

    def test_returns_none_when_disabled(self, fake_hass):
        """Returns None when circadian is disabled."""
        controller = _make_controller(fake_hass, enabled=False)
        assert controller.get_expected_night_kelvin() is None

    def test_returns_current_kelvin_when_enabled(self, fake_hass):
        """Returns current kelvin when enabled."""
        fake_hass.states.set(
            "sun.sun",
            FakeState(state="below_horizon", attributes={"elevation": -10.0}),
        )
        controller = _make_controller(fake_hass, enabled=True, min_kelvin=2700)
        kelvin = controller.get_expected_night_kelvin()

        assert kelvin >= 2700  # At or above min kelvin at night


# ===================================================================
#  Kelvin range
# ===================================================================


class TestKelvinRange:
    """Tests for kelvin range configuration."""

    def test_custom_min_kelvin(self, fake_hass):
        """Custom min_kelvin is respected."""
        fake_hass.states.set(
            "sun.sun",
            FakeState(state="below_horizon", attributes={"elevation": -10.0}),
        )
        controller = _make_controller(fake_hass, enabled=True, min_kelvin=3000, max_kelvin=6000)
        kelvin, _ = controller.get_kelvin()

        assert kelvin >= 3000  # At or above custom min

    def test_custom_max_kelvin(self, fake_hass):
        """Custom max_kelvin is respected."""
        fake_hass.states.set(
            "sun.sun",
            FakeState(state="above_horizon", attributes={"elevation": 90.0}),
        )
        controller = _make_controller(fake_hass, enabled=True, min_kelvin=3000, max_kelvin=6000)
        kelvin, _ = controller.get_kelvin()

        assert kelvin == 6000  # Custom max

    def test_narrow_kelvin_range(self, fake_hass):
        """Narrow kelvin range still works correctly."""
        fake_hass.states.set(
            "sun.sun",
            FakeState(state="above_horizon", attributes={"elevation": 45.0}),
        )
        controller = _make_controller(fake_hass, enabled=True, min_kelvin=4000, max_kelvin=4500)
        kelvin, _ = controller.get_kelvin()

        assert 4000 <= kelvin <= 4500
