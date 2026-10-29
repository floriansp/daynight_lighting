"""Root conftest: mock the homeassistant package so tests can import
custom_components.daynight_lighting.* without a full HA installation.

This file is loaded by pytest *before* any test module collection, so
sys.modules entries are in place when the imports happen.
"""

from __future__ import annotations

import sys
from types import ModuleType
from unittest.mock import MagicMock

# ---------------------------------------------------------------------------
#  Build a tree of fake homeassistant.* modules
# ---------------------------------------------------------------------------

_HA_MODULES: dict[str, ModuleType] = {}


def _get_or_create(name: str) -> ModuleType:
    """Return an existing fake module or create a new one."""
    if name in _HA_MODULES:
        return _HA_MODULES[name]
    mod = ModuleType(name)
    _HA_MODULES[name] = mod
    sys.modules[name] = mod
    # If this is a sub-module, also set it as an attribute on the parent
    if "." in name:
        parent_name = name.rsplit(".", 1)[0]
        child_attr = name.rsplit(".", 1)[1]
        parent = _get_or_create(parent_name)
        setattr(parent, child_attr, mod)
    return mod


# -- create all modules that custom_components.daynight_lighting touches --
_module_names = [
    "homeassistant",
    "homeassistant.config_entries",
    "homeassistant.core",
    "homeassistant.const",
    "homeassistant.data_entry_flow",
    "homeassistant.util",
    "homeassistant.util.dt",
    "homeassistant.helpers",
    "homeassistant.helpers.dispatcher",
    "homeassistant.helpers.entity",
    "homeassistant.helpers.entity_platform",
    "homeassistant.helpers.event",
    "homeassistant.helpers.restore_state",
    "homeassistant.helpers.storage",
    "homeassistant.helpers.selector",
    "homeassistant.helpers.area_registry",
    "homeassistant.helpers.entity_registry",
    "homeassistant.components",
    "homeassistant.components.binary_sensor",
    "homeassistant.components.button",
    "homeassistant.components.light",
    "homeassistant.components.number",
    "homeassistant.components.sensor",
    "homeassistant.components.switch",
    "homeassistant.config_entries",
    "voluptuous",
    "voluptuous.validators",
]

for _name in _module_names:
    _get_or_create(_name)

# ---------------------------------------------------------------------------
#  homeassistant.data_entry_flow — provide a working `section` stub
# ---------------------------------------------------------------------------

_def = sys.modules["homeassistant.data_entry_flow"]


def _stub_section(schema, options=None):
    """Stub for homeassistant.data_entry_flow.section.

    In the real HA, ``section()`` wraps a vol.Schema to render a
    collapsible UI group.  For tests we just return the schema itself
    so that the mock vol.Schema can accept it.
    """
    return schema


_def.section = _stub_section  # type: ignore[attr-defined]

# ---------------------------------------------------------------------------
#  Populate commonly imported names so `from homeassistant.X import Y` works
# ---------------------------------------------------------------------------

# homeassistant.const
_const = sys.modules["homeassistant.const"]
_const.STATE_ON = "on"  # type: ignore[attr-defined]
_const.STATE_OFF = "off"  # type: ignore[attr-defined]
_const.STATE_UNAVAILABLE = "unavailable"  # type: ignore[attr-defined]
_const.STATE_UNKNOWN = "unknown"  # type: ignore[attr-defined]

# homeassistant.core
_core = sys.modules["homeassistant.core"]
_core.HomeAssistant = MagicMock  # type: ignore[attr-defined]
_core.callback = lambda fn: fn  # type: ignore[attr-defined]  # identity decorator
_core.ServiceCall = MagicMock  # type: ignore[attr-defined]

# homeassistant.config_entries
_cfg = sys.modules["homeassistant.config_entries"]
_cfg.ConfigEntry = MagicMock  # type: ignore[attr-defined]
_cfg.ConfigEntryState = MagicMock()  # type: ignore[attr-defined]  # instance, so .LOADED etc. auto-create


# ConfigFlow / OptionsFlow need real base classes so subclassing with
# keyword args (domain=DOMAIN) works.  HA's ConfigFlow uses a metaclass
# that consumes the ``domain`` kwarg; we replicate just enough.
class _FlowMeta(type):
    """Metaclass that silently accepts and ignores extra keyword args like ``domain``."""
    def __new__(mcs, name, bases, namespace, **kwargs):
        return super().__new__(mcs, name, bases, namespace)
    def __init__(cls, name, bases, namespace, **kwargs):
        super().__init__(name, bases, namespace)


class _ConfigFlow(metaclass=_FlowMeta):
    """Minimal stub for homeassistant.config_entries.ConfigFlow."""
    pass


class _OptionsFlow:
    """Minimal stub for homeassistant.config_entries.OptionsFlow."""
    pass


class _ConfigFlowResult(dict):
    """Minimal stub for ConfigFlowResult (just a dict)."""
    pass


_cfg.ConfigFlow = _ConfigFlow  # type: ignore[attr-defined]
_cfg.OptionsFlow = _OptionsFlow  # type: ignore[attr-defined]
_cfg.ConfigFlowResult = _ConfigFlowResult  # type: ignore[attr-defined]

# homeassistant.helpers.storage
_storage = sys.modules["homeassistant.helpers.storage"]
_storage.Store = MagicMock  # type: ignore[attr-defined]

# homeassistant.helpers.entity
_entity_mod = sys.modules["homeassistant.helpers.entity"]
_entity_mod.DeviceInfo = MagicMock  # type: ignore[attr-defined]

# homeassistant.helpers.entity_platform
_eplatform = sys.modules["homeassistant.helpers.entity_platform"]
_eplatform.AddEntitiesCallback = MagicMock  # type: ignore[attr-defined]

# homeassistant.helpers.event
_event = sys.modules["homeassistant.helpers.event"]
_event.async_track_state_change_event = MagicMock  # type: ignore[attr-defined]
_event.async_track_time_change = MagicMock  # type: ignore[attr-defined]

# homeassistant.helpers.restore_state
_restore = sys.modules["homeassistant.helpers.restore_state"]


class _RestoreEntity:
    """Minimal stub for RestoreEntity with async lifecycle methods."""
    async def async_added_to_hass(self):
        pass
    async def async_will_remove_from_hass(self):
        pass
    async def async_get_last_state(self):
        return None


_restore.RestoreEntity = _RestoreEntity  # type: ignore[attr-defined]

# homeassistant.helpers.entity_registry
_er = sys.modules["homeassistant.helpers.entity_registry"]
_er.async_get = MagicMock  # type: ignore[attr-defined]

# homeassistant.helpers.area_registry
_ar = sys.modules["homeassistant.helpers.area_registry"]
_ar.async_get = MagicMock  # type: ignore[attr-defined]

# homeassistant.helpers.selector — used by config_flow; provide enough stubs.
# Use simple callables (not MagicMock) because HA selectors are instantiated
# with config objects: EntitySelector(EntitySelectorConfig(...)).  MagicMock
# as a class breaks when another MagicMock is passed to its __init__ (spec error).
_sel = sys.modules["homeassistant.helpers.selector"]


class _StubSelector:
    """Accepts any args/kwargs and acts as a no-op selector."""
    def __init__(self, *args, **kwargs):
        pass


for _sel_name in [
    "EntitySelector",
    "EntitySelectorConfig",
    "AreaSelector",
    "AreaSelectorConfig",
    "NumberSelector",
    "NumberSelectorConfig",
    "NumberSelectorMode",
    "BooleanSelector",
    "SelectSelector",
    "SelectSelectorConfig",
    "SelectSelectorMode",
    "TextSelector",
    "TextSelectorConfig",
    "TimeSelector",
    "TimeSelectorConfig",
]:
    setattr(_sel, _sel_name, _StubSelector)

# homeassistant.components.light
_light = sys.modules["homeassistant.components.light"]
_light.ATTR_BRIGHTNESS_PCT = "brightness_pct"  # type: ignore[attr-defined]
_light.ATTR_BRIGHTNESS = "brightness"  # type: ignore[attr-defined]
_light.ATTR_COLOR_TEMP_KELVIN = "color_temp_kelvin"  # type: ignore[attr-defined]

# homeassistant.components.switch
_switch = sys.modules["homeassistant.components.switch"]
class _SwitchEntity:
    """Minimal stub for SwitchEntity with lifecycle methods."""
    _attr_is_on = False
    async def async_added_to_hass(self):
        pass
    async def async_will_remove_from_hass(self):
        pass
    def async_write_ha_state(self):
        pass


_switch.SwitchEntity = _SwitchEntity  # type: ignore[attr-defined]

# homeassistant.components.sensor
_sensor = sys.modules["homeassistant.components.sensor"]


class _SensorEntity:
    """Minimal stub for SensorEntity with lifecycle methods."""
    _attr_native_value = None

    async def async_added_to_hass(self):
        pass

    async def async_will_remove_from_hass(self):
        pass

    def async_write_ha_state(self):
        pass

    def async_on_remove(self, func):
        self.__dict__.setdefault("_on_remove_callbacks", []).append(func)

    # Mirror the attribute-backed properties of homeassistant.helpers.Entity
    @property
    def unique_id(self):
        return getattr(self, "_attr_unique_id", None)

    @property
    def should_poll(self):
        return getattr(self, "_attr_should_poll", True)


class _SensorDeviceClass:
    ENUM = "enum"
    ILLUMINANCE = "illuminance"


class _SensorStateClass:
    MEASUREMENT = "measurement"


_sensor.SensorEntity = _SensorEntity  # type: ignore[attr-defined]
_sensor.SensorDeviceClass = _SensorDeviceClass  # type: ignore[attr-defined]
_sensor.SensorStateClass = _SensorStateClass  # type: ignore[attr-defined]

# homeassistant.components.number
_number = sys.modules["homeassistant.components.number"]


class _NumberEntity(_SensorEntity):
    """Minimal stub for NumberEntity; shares the entity basics."""
    hass = None


class _NumberMode:
    SLIDER = "slider"
    BOX = "box"


_number.NumberEntity = _NumberEntity  # type: ignore[attr-defined]
_number.NumberMode = _NumberMode  # type: ignore[attr-defined]

# homeassistant.components.button
_button = sys.modules["homeassistant.components.button"]


class _ButtonEntity(_SensorEntity):
    """Minimal stub for ButtonEntity; shares the entity basics."""


_button.ButtonEntity = _ButtonEntity  # type: ignore[attr-defined]

# homeassistant.components.binary_sensor
_binary = sys.modules["homeassistant.components.binary_sensor"]


class _BinarySensorEntity(_SensorEntity):
    """Minimal stub for BinarySensorEntity; shares the entity basics."""
    _attr_is_on = False


class _BinarySensorDeviceClass:
    PROBLEM = "problem"


_binary.BinarySensorEntity = _BinarySensorEntity  # type: ignore[attr-defined]
_binary.BinarySensorDeviceClass = _BinarySensorDeviceClass  # type: ignore[attr-defined]

# homeassistant.helpers.dispatcher — small working implementation so tests
# can exercise the signal path instead of only asserting a mock was called.
_dispatcher = sys.modules["homeassistant.helpers.dispatcher"]
_dispatch_targets: dict[str, list] = {}


def _async_dispatcher_connect(hass, signal, target):
    _dispatch_targets.setdefault(signal, []).append(target)

    def _unsubscribe():
        if target in _dispatch_targets.get(signal, []):
            _dispatch_targets[signal].remove(target)

    return _unsubscribe


def _async_dispatcher_send(hass, signal, *args):
    for target in list(_dispatch_targets.get(signal, [])):
        target(*args)


_dispatcher.async_dispatcher_connect = _async_dispatcher_connect  # type: ignore[attr-defined]
_dispatcher.async_dispatcher_send = _async_dispatcher_send  # type: ignore[attr-defined]

# homeassistant.util.dt
_dt = sys.modules["homeassistant.util.dt"]
import homeassistant.util.dt as _dt_real  # noqa: this IS our fake
# provide real-ish implementations so schedule.py can work
from datetime import datetime, timezone

_dt.now = lambda: datetime.now()  # type: ignore[attr-defined]
_dt.utcnow = lambda: datetime.now(timezone.utc)  # type: ignore[attr-defined]
_dt.parse_datetime = MagicMock  # type: ignore[attr-defined]
_dt.as_local = lambda x: x  # type: ignore[attr-defined]

# homeassistant (top-level) – used by `from homeassistant import config_entries`
_ha = sys.modules["homeassistant"]
_ha.config_entries = sys.modules["homeassistant.config_entries"]  # type: ignore[attr-defined]

# voluptuous – used by services.py
# Replace the ModuleType stub with a MagicMock so any attribute access
# (vol.Any, vol.Schema, vol.Optional, vol.ALLOW_EXTRA, …) auto-creates mocks.
_vol_mock = MagicMock()
_vol_mock.__name__ = "voluptuous"  # keep module-like name
sys.modules["voluptuous"] = _vol_mock  # type: ignore[assignment]
sys.modules["voluptuous.validators"] = MagicMock()  # type: ignore[assignment]
