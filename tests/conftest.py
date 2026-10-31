"""Shared fixtures for DayNight Lighting unit and functional tests."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from custom_components.daynight_lighting.const import DOMAIN


# ---------------------------------------------------------------------------
#  Lightweight mock for hass.states
# ---------------------------------------------------------------------------

class FakeState:
    """Minimal stand-in for homeassistant.core.State."""

    def __init__(
        self,
        state: str = "on",
        attributes: dict[str, Any] | None = None,
    ) -> None:
        self.state = state
        self.attributes = attributes or {}


class FakeStates:
    """Minimal stand-in for hass.states (get only)."""

    def __init__(self) -> None:
        self._registry: dict[str, FakeState] = {}

    def set(self, entity_id: str, state: FakeState) -> None:
        self._registry[entity_id] = state

    def get(self, entity_id: str) -> FakeState | None:
        return self._registry.get(entity_id)


class FakeToggle:
    """Stand-in for an instance toggle entity (manual control, control switches).

    Mirrors the public surface the integration reads: ``is_on`` and, for
    manual control, ``is_detected_override`` and ``async_set_manual_control``.
    """

    def __init__(self, _attr_is_on: bool = False, **attrs: Any) -> None:
        self._attr_is_on = _attr_is_on
        self._detected = False
        for key, value in attrs.items():
            setattr(self, key, value)

    @property
    def is_on(self) -> bool:
        return self._attr_is_on

    @property
    def is_detected_override(self) -> bool:
        return self._attr_is_on and self._detected

    def async_set_manual_control(self, on: bool, *, detected: bool = False) -> None:
        self._attr_is_on = on
        self._detected = on and detected


# ---------------------------------------------------------------------------
#  Lightweight mock for HomeAssistant
# ---------------------------------------------------------------------------

class FakeEvent:
    """Minimal stand-in for homeassistant.core.Event."""

    def __init__(self, event_type: str, data: dict[str, Any]) -> None:
        self.event_type = event_type
        self.data = data


class FakeEventBus:
    """Records fired events and dispatches registered listeners."""

    def __init__(self) -> None:
        self.fired: list[tuple[str, dict[str, Any]]] = []
        self._listeners: dict[str, list] = {}

    def async_fire(self, event_type: str, event_data: dict[str, Any] | None = None):
        data = event_data or {}
        self.fired.append((event_type, data))
        event = FakeEvent(event_type, data)
        for listener in list(self._listeners.get(event_type, [])):
            listener(event)

    def async_listen(self, event_type: str, listener) -> callable:
        self._listeners.setdefault(event_type, []).append(listener)

        def _remove() -> None:
            listeners = self._listeners.get(event_type, [])
            if listener in listeners:
                listeners.remove(listener)

        return _remove

    def events_of_type(self, event_type: str) -> list[dict[str, Any]]:
        return [data for name, data in self.fired if name == event_type]


class FakeHass:
    """Minimal stand-in for homeassistant.core.HomeAssistant.

    Only provides ``states``, ``data``, ``bus``, and mock ``loop`` /
    ``services`` — enough for unit and functional tests without the full
    HA runtime.
    """

    def __init__(self) -> None:
        self.states = FakeStates()
        self.data: dict[str, Any] = {}
        self.loop = MagicMock()
        self.services = MagicMock()
        self.bus = FakeEventBus()

    def async_create_task(self, coro):
        """No-op for unit tests."""


# ---------------------------------------------------------------------------
#  Lightweight mock for homeassistant.helpers.storage.Store
# ---------------------------------------------------------------------------

class FakeStore:
    """Minimal stand-in for homeassistant.helpers.storage.Store."""

    def __init__(self) -> None:
        self._data: dict[str, Any] | None = None

    async def async_load(self) -> dict[str, Any] | None:
        return self._data

    def async_delay_save(self, data_func, delay=0):
        """Immediately capture the data (no actual delay)."""
        self._data = data_func()


# ---------------------------------------------------------------------------
#  Mock ConfigEntry
# ---------------------------------------------------------------------------

class MockConfigEntry:
    """Minimal stand-in for homeassistant.config_entries.ConfigEntry."""

    def __init__(
        self,
        entry_id: str = "test_entry",
        options: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
    ) -> None:
        self.entry_id = entry_id
        self.options = options or {}
        self.data = data or {}


# ---------------------------------------------------------------------------
#  Default options for functional tests
# ---------------------------------------------------------------------------

DEFAULT_FUNCTIONAL_OPTIONS: dict[str, Any] = {
    "instance_name": "Test",
    "lights": ["light.a", "light.b"],
    "light_sensor": "sensor.lux",
    "motion_sensor": "binary_sensor.motion",
    "night_mode_start": "sun_below_horizon",
    "lux_on": 10.0,
    "lux_off": 100.0,
    "day_min_brightness": 10,
    "day_max_brightness": 100,
    "night_brightness": 80,
    "circadian_enabled": True,
    "circadian_min_kelvin": 2700,
    "circadian_max_kelvin": 5500,
    "motion_off_delay_min": 5,
    "on_enter_night": "leave",
}


# ---------------------------------------------------------------------------
#  Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def fake_hass() -> FakeHass:
    """Provide a lightweight mock HomeAssistant."""
    return FakeHass()


@pytest.fixture
def fake_store() -> FakeStore:
    """Provide a lightweight mock Store."""
    return FakeStore()


# ---------------------------------------------------------------------------
#  Switch factory fixture (functional tests)
# ---------------------------------------------------------------------------

@pytest.fixture
def make_switch(fake_hass, fake_store):
    """Factory to create a fully mocked DayNightLightingSwitch.

    Returns ``(switch, ctrl_brightness, ctrl_color)``.
    The ``day_mode`` flag controls whether ``sun.sun`` is above or
    below the horizon (used with ``sun_below_horizon`` schedule mode).
    """
    from custom_components.daynight_lighting.switch import (
        DayNightLightingSwitch,
    )
    from custom_components.daynight_lighting.state_controller import StateController

    def _factory(
        options: dict[str, Any] | None = None,
        *,
        day_mode: bool = True,
        sun_elevation: float = 30.0,
    ):
        opts = {**DEFAULT_FUNCTIONAL_OPTIONS, **(options or {})}
        entry = MockConfigEntry(
            options=opts, data={"instance_name": "Test"}
        )

        ctrl_brightness = FakeToggle(
            _attr_is_on=True, async_write_ha_state=lambda: None
        )
        ctrl_color = FakeToggle(
            _attr_is_on=True, async_write_ha_state=lambda: None
        )

        # Wire up hass.data[DOMAIN][entry_id]
        fake_hass.data = {
            DOMAIN: {
                entry.entry_id: {
                    "control_brightness_switch": ctrl_brightness,
                    "control_color_switch": ctrl_color,
                }
            }
        }

        # Sun state → controls day/night in sun_below_horizon mode
        sun_state = "above_horizon" if day_mode else "below_horizon"
        fake_hass.states.set(
            "sun.sun",
            FakeState(
                state=sun_state,
                attributes={
                    "elevation": sun_elevation,
                    "next_rising": "2026-06-16T05:15:00+00:00",
                },
            ),
        )

        # Create switch
        switch = DayNightLightingSwitch(entry, "Test")
        switch.hass = fake_hass
        switch.async_write_ha_state = lambda: None
        switch._attr_is_on = True

        # Inject state controller with fake store
        state_ctrl = StateController(fake_hass, entry.entry_id, "Test")
        state_ctrl._store = fake_store
        switch._state_ctrl_instance = state_ctrl

        fake_hass.data[DOMAIN][entry.entry_id]["main_switch"] = switch

        return switch, ctrl_brightness, ctrl_color

    return _factory
