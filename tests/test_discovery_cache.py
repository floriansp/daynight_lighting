"""Regression tests for the area-discovery cache in the main switch.

Area discovery used to re-scan the registries on every read of
``extra_state_attributes`` and every sensor resolution, flooding the debug log
("Found N motion sensors …"). It is now cached, and invalidated event-driven
on registry updates (a newly added lamp/sensor is adopted within seconds) with
only a long safety-net TTL. These tests lock that in.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from custom_components.daynight_lighting.switch import (
    EVENT_AREA_REGISTRY_UPDATED,
    EVENT_ENTITY_REGISTRY_UPDATED,
    REGISTRY_DEBOUNCE_SECONDS,
)

from tests.conftest import FakeState

_AREA_DISCOVERY = "custom_components.daynight_lighting.area_discovery"


def _area_options() -> dict:
    return {"area_id": "kitchen", "included_lights": ["light.a"]}


class TestAreaDiscoveryCache:
    """The discovery results are exposed once and scanned at most once per TTL."""

    def test_attributes_include_discovery_info(self, make_switch, fake_hass):
        switch, *_ = make_switch(options=_area_options(), day_mode=True)
        fake_hass.states.set(
            "binary_sensor.kitchen_motion", FakeState(state="on")
        )

        with patch(
            f"{_AREA_DISCOVERY}.get_area_name", return_value="Kitchen"
        ), patch(
            f"{_AREA_DISCOVERY}.get_lights_in_area",
            return_value=["light.a", "light.b"],
        ), patch(
            f"{_AREA_DISCOVERY}.get_motion_sensors_in_area",
            return_value=["binary_sensor.kitchen_motion"],
        ), patch(
            f"{_AREA_DISCOVERY}.get_illuminance_sensors_in_area",
            return_value=["sensor.kitchen_lux"],
        ):
            attrs = switch.extra_state_attributes

        assert attrs["area"] == "Kitchen"
        assert attrs["area_id"] == "kitchen"
        assert attrs["area_lights_total"] == 2
        assert attrs["area_lights_controlled"] == 1
        assert attrs["motion_sensors_discovered"] == [
            "binary_sensor.kitchen_motion"
        ]
        assert attrs["illuminance_sensors_discovered"] == ["sensor.kitchen_lux"]
        assert attrs["motion_sensors_active"] == ["binary_sensor.kitchen_motion"]

    def test_discovery_scans_once_per_ttl(self, make_switch, fake_hass):
        switch, *_ = make_switch(options=_area_options(), day_mode=True)

        calls = {"motion": 0}

        def _fake_motion(hass, area_id, instance_name):
            calls["motion"] += 1
            return ["binary_sensor.kitchen_motion"]

        with patch(
            f"{_AREA_DISCOVERY}.get_area_name", return_value="Kitchen"
        ), patch(
            f"{_AREA_DISCOVERY}.get_lights_in_area",
            return_value=["light.a"],
        ), patch(
            f"{_AREA_DISCOVERY}.get_motion_sensors_in_area",
            side_effect=_fake_motion,
        ), patch(
            f"{_AREA_DISCOVERY}.get_illuminance_sensors_in_area",
            return_value=[],
        ):
            switch.extra_state_attributes
            switch.extra_state_attributes

        # Two reads within the TTL → the registry was scanned only once.
        assert calls["motion"] == 1

    def test_sensor_resolution_reads_the_same_cache(self, make_switch, fake_hass):
        switch, *_ = make_switch(options=_area_options(), day_mode=True)

        with patch(
            f"{_AREA_DISCOVERY}.get_area_name", return_value="Kitchen"
        ), patch(
            f"{_AREA_DISCOVERY}.get_lights_in_area",
            return_value=["light.a"],
        ), patch(
            f"{_AREA_DISCOVERY}.get_motion_sensors_in_area",
            return_value=["binary_sensor.kitchen_motion"],
        ), patch(
            f"{_AREA_DISCOVERY}.get_illuminance_sensors_in_area",
            return_value=[],
        ):
            # Resolving motion sensors goes through the cached discovery.
            motion_ids = switch._resolve_sensor_ids("motion_sensor")

        assert motion_ids == ["binary_sensor.kitchen_motion", "binary_sensor.motion"]

    def test_sensor_resolution_excludes_configured_motion_sensors(
        self, make_switch, fake_hass
    ):
        switch, *_ = make_switch(
            options={
                "area_id": "kitchen",
                "included_lights": ["light.a"],
                "excluded_motion_sensors": ["binary_sensor.cam_motion"],
            },
            day_mode=True,
        )

        with patch(
            f"{_AREA_DISCOVERY}.get_area_name", return_value="Kitchen"
        ), patch(
            f"{_AREA_DISCOVERY}.get_lights_in_area",
            return_value=["light.a"],
        ), patch(
            f"{_AREA_DISCOVERY}.get_motion_sensors_in_area",
            return_value=[
                "binary_sensor.cam_motion",
                "binary_sensor.kitchen_motion",
            ],
        ), patch(
            f"{_AREA_DISCOVERY}.get_illuminance_sensors_in_area",
            return_value=[],
        ):
            motion_ids = switch._resolve_sensor_ids("motion_sensor")

        # The excluded camera sensor is dropped; the manual sensor still added.
        assert motion_ids == ["binary_sensor.kitchen_motion", "binary_sensor.motion"]

    def test_excluded_motion_sensors_do_not_affect_illuminance(
        self, make_switch, fake_hass
    ):
        switch, *_ = make_switch(
            options={
                "area_id": "kitchen",
                "included_lights": ["light.a"],
                "excluded_motion_sensors": ["binary_sensor.cam_motion"],
            },
            day_mode=True,
        )

        with patch(
            f"{_AREA_DISCOVERY}.get_area_name", return_value="Kitchen"
        ), patch(
            f"{_AREA_DISCOVERY}.get_lights_in_area",
            return_value=["light.a"],
        ), patch(
            f"{_AREA_DISCOVERY}.get_motion_sensors_in_area",
            return_value=["binary_sensor.cam_motion"],
        ), patch(
            f"{_AREA_DISCOVERY}.get_illuminance_sensors_in_area",
            return_value=["sensor.kitchen_lux"],
        ):
            lux_ids = switch._resolve_sensor_ids("light_sensor")

        # Illuminance sensors are not filtered by excluded_motion_sensors.
        assert lux_ids == ["sensor.kitchen_lux", "sensor.lux"]

    def test_cache_is_dropped_on_options_change(self, make_switch, fake_hass):
        switch, *_ = make_switch(options=_area_options(), day_mode=True)

        calls = {"motion": 0}

        def _fake_motion(hass, area_id, instance_name):
            calls["motion"] += 1
            return ["binary_sensor.kitchen_motion"]

        with patch(
            f"{_AREA_DISCOVERY}.get_area_name", return_value="Kitchen"
        ), patch(
            f"{_AREA_DISCOVERY}.get_lights_in_area",
            return_value=["light.a"],
        ), patch(
            f"{_AREA_DISCOVERY}.get_motion_sensors_in_area",
            side_effect=_fake_motion,
        ), patch(
            f"{_AREA_DISCOVERY}.get_illuminance_sensors_in_area",
            return_value=[],
        ):
            switch.extra_state_attributes
            # A live options change rebuilds the option caches.
            switch._invalidate_option_caches()
            switch.extra_state_attributes

        assert calls["motion"] == 2


class TestRegistryDrivenDiscovery:
    """A registry change re-discovers and adopts new lamps/sensors immediately."""

    def test_new_light_is_adopted_after_registry_change(
        self, make_switch, fake_hass
    ):
        switch, *_ = make_switch(options={"area_id": "kitchen"}, day_mode=True)
        fake_hass.states.set("sensor.lux", FakeState(state="50"))

        area_lights = ["light.a"]

        def _fake_lights(hass, area_id, instance_name):
            return list(area_lights)

        with patch(
            f"{_AREA_DISCOVERY}.get_area_name", return_value="Kitchen"
        ), patch(
            f"{_AREA_DISCOVERY}.get_lights_in_area",
            side_effect=_fake_lights,
        ), patch(
            f"{_AREA_DISCOVERY}.get_motion_sensors_in_area",
            return_value=[],
        ), patch(
            f"{_AREA_DISCOVERY}.get_illuminance_sensors_in_area",
            return_value=[],
        ):
            switch._start_listeners()
            assert switch._lights.get_lights_list() == ["light.a"]

            # A new light is added to the area's entity registry.
            area_lights.append("light.b")
            fake_hass.bus.async_fire(EVENT_ENTITY_REGISTRY_UPDATED, {})

            # The event only armed the debounced re-scan; run it.
            switch._apply_registry_change()

            assert switch._lights.get_lights_list() == ["light.a", "light.b"]

    def test_unrelated_registry_change_does_not_restart(
        self, make_switch, fake_hass
    ):
        """A registry event that leaves the entity set unchanged (e.g. an area
        rename) must not re-apply the lights."""
        switch, *_ = make_switch(options=_area_options(), day_mode=True)
        fake_hass.states.set("sensor.lux", FakeState(state="50"))

        with patch(
            f"{_AREA_DISCOVERY}.get_area_name", return_value="Kitchen"
        ), patch(
            f"{_AREA_DISCOVERY}.get_lights_in_area",
            return_value=["light.a"],
        ), patch(
            f"{_AREA_DISCOVERY}.get_motion_sensors_in_area",
            return_value=[],
        ), patch(
            f"{_AREA_DISCOVERY}.get_illuminance_sensors_in_area",
            return_value=[],
        ):
            switch._start_listeners()
            with patch.object(switch, "_start_listeners") as restart:
                fake_hass.bus.async_fire(EVENT_AREA_REGISTRY_UPDATED, {})
                switch._apply_registry_change()
            restart.assert_not_called()

    def test_registry_events_are_debounced(self, make_switch, fake_hass):
        """A burst of registry events arms one timer, not a scan per event."""
        switch, *_ = make_switch(options=_area_options(), day_mode=True)
        fake_hass.states.set("sensor.lux", FakeState(state="50"))

        with patch(
            f"{_AREA_DISCOVERY}.get_area_name", return_value="Kitchen"
        ), patch(
            f"{_AREA_DISCOVERY}.get_lights_in_area",
            return_value=["light.a"],
        ), patch(
            f"{_AREA_DISCOVERY}.get_motion_sensors_in_area",
            return_value=[],
        ), patch(
            f"{_AREA_DISCOVERY}.get_illuminance_sensors_in_area",
            return_value=[],
        ):
            switch._start_listeners()

            handles: list = []

            def _fake_call_later(delay, callback):
                handle = MagicMock()
                handles.append((handle, delay, callback))
                return handle

            fake_hass.loop.call_later.side_effect = _fake_call_later

            fake_hass.bus.async_fire(EVENT_ENTITY_REGISTRY_UPDATED, {})
            fake_hass.bus.async_fire(EVENT_ENTITY_REGISTRY_UPDATED, {})
            fake_hass.bus.async_fire(EVENT_AREA_REGISTRY_UPDATED, {})

        # Each event re-armed the timer; the earlier ones were cancelled.
        assert len(handles) == 3
        assert handles[0][0].cancel.called is True
        assert handles[1][0].cancel.called is True
        assert handles[2][0].cancel.called is False
        assert handles[2][1] == REGISTRY_DEBOUNCE_SECONDS

    def test_registry_events_are_ignored_when_switch_is_off(
        self, make_switch, fake_hass
    ):
        """A turned-off instance must not arm a re-scan at all."""
        switch, *_ = make_switch(options=_area_options(), day_mode=True)
        switch._attr_is_on = False

        switch._on_registry_changed(None)

        fake_hass.loop.call_later.assert_not_called()

    def test_registers_entity_device_and_area_listeners(
        self, make_switch, fake_hass
    ):
        switch, *_ = make_switch(options=_area_options(), day_mode=True)
        fake_hass.states.set("sensor.lux", FakeState(state="50"))

        with patch(
            f"{_AREA_DISCOVERY}.get_area_name", return_value="Kitchen"
        ), patch(
            f"{_AREA_DISCOVERY}.get_lights_in_area",
            return_value=["light.a"],
        ), patch(
            f"{_AREA_DISCOVERY}.get_motion_sensors_in_area",
            return_value=[],
        ), patch(
            f"{_AREA_DISCOVERY}.get_illuminance_sensors_in_area",
            return_value=[],
        ):
            switch._start_listeners()

        listeners = fake_hass.bus._listeners
        assert EVENT_ENTITY_REGISTRY_UPDATED in listeners
        assert "device_registry_updated" in listeners
        assert EVENT_AREA_REGISTRY_UPDATED in listeners
