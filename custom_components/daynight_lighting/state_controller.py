"""Persistent state controller for DayNight Lighting.

Tracks which lights are controlled by this integration instance across
Home Assistant restarts.  Uses HA's ``Store`` for file-based persistence.

* **lights_we_control** – lights we turned on or are currently managing.
* **held_lights** – lights we must not touch, mapped to the reason they were
  held (``"detected"`` for an external intervention, ``"service"`` for a
  ``turn_on``/``turn_off`` with ``hold: true``). A service hold lives until
  an explicit release or a mode change; a detected hold survives the mode
  change and only ends through an explicit release.
"""

from __future__ import annotations

import logging
from typing import Any, TYPE_CHECKING

from homeassistant.helpers.storage import Store

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

STORAGE_VERSION = 1
SAVE_DELAY_SECONDS = 2

# Reasons a light can be held. Persisted alongside the entity_id.
HOLD_REASON_DETECTED = "detected"
HOLD_REASON_SERVICE = "service"


class StateController:
    """Persistent state: tracks which lights we turned on / are controlling."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry_id: str,
        instance_name: str = "",
    ) -> None:
        self._hass = hass
        self._instance_name = instance_name
        self._store: Store = Store(
            hass, STORAGE_VERSION, f"daynight_lighting_{entry_id}"
        )
        self._lights_we_control: set[str] = set()
        self._held_lights: dict[str, str] = {}
        self._lux_calibration: float | None = None  # LUX at 100% brightness
        # Expected state per light: {light_id: {"brightness_pct": int, "mode": str, "timestamp": float}}
        # Used for external control detection - persists across reboots
        self._expected_states: dict[str, dict[str, Any]] = {}

    # ------------------------------------------------------------------
    #  Load / Save
    # ------------------------------------------------------------------

    async def async_load(self) -> None:
        """Load persisted state from HA storage."""
        data: dict[str, Any] | None = await self._store.async_load()
        if data:
            self._lights_we_control = set(data.get("lights_we_control", []))
            self._held_lights = self._migrate_held_lights(data.get("held_lights"))
            self._lux_calibration = data.get("lux_calibration")
            # Load expected states, filtering out stale entries (older than 24 hours)
            expected_states = data.get("expected_states", {})
            now = self._hass.loop.time() if hasattr(self._hass, 'loop') else 0
            self._expected_states = {
                k: v for k, v in expected_states.items()
                if isinstance(v, dict) and now - v.get("timestamp", 0) < 86400
            }
            _LOGGER.debug(
                "[%s] State loaded: %d controlled, %d held, %d expected, lux_cal=%s",
                self._instance_name,
                len(self._lights_we_control),
                len(self._held_lights),
                len(self._expected_states),
                f"{self._lux_calibration:.1f}" if self._lux_calibration else "None",
            )

    @staticmethod
    def _migrate_held_lights(held: Any) -> dict[str, str]:
        """Normalise persisted ``held_lights`` into ``{lid: reason}``.

        Older versions stored a plain list of entity_ids. Those entries were
        created by services, so they migrate to the ``"service"`` reason.
        """
        if isinstance(held, dict):
            return {str(lid): str(reason) for lid, reason in held.items()}
        if isinstance(held, (list, set, tuple)):
            return {str(lid): HOLD_REASON_SERVICE for lid in held}
        return {}

    def _schedule_save(self) -> None:
        """Debounced save to HA storage."""
        self._store.async_delay_save(
            self._data_to_save, delay=SAVE_DELAY_SECONDS
        )

    def _data_to_save(self) -> dict[str, Any]:
        """Build data dict for storage."""
        return {
            "lights_we_control": sorted(self._lights_we_control),
            "held_lights": dict(sorted(self._held_lights.items())),
            "lux_calibration": self._lux_calibration,
            "expected_states": self._expected_states,
        }

    # ------------------------------------------------------------------
    #  Mark / unmark
    # ------------------------------------------------------------------

    def mark_controlled(self, lights: list[str]) -> None:
        """Mark lights as controlled by us (we turned them on / manage them)."""
        self._lights_we_control.update(lights)
        self._schedule_save()

    def unmark_controlled(self, lights: list[str]) -> None:
        """Remove lights from our control (we turned them off / released)."""
        self._lights_we_control -= set(lights)
        self._schedule_save()

    # ------------------------------------------------------------------
    #  Holds (a light we must not touch, until released or the mode changes)
    # ------------------------------------------------------------------

    def set_hold(self, lights: list[str], *, reason: str = HOLD_REASON_SERVICE) -> None:
        """Hold *lights* in place until the phase ends.

        The *reason* is recorded so the sensors can show *why* a light is held:
        ``"detected"`` for a foreign intervention, ``"service"`` for a
        ``turn_on``/``turn_off`` with ``hold: true``.
        """
        if not lights:
            return
        for lid in lights:
            self._held_lights[lid] = reason
        self._schedule_save()

    def release_hold(self, lights: list[str] | None = None) -> None:
        """Release holds: all lights when *lights* is None, else just those."""
        if lights is None:
            removed = bool(self._held_lights)
            self._held_lights.clear()
        else:
            removed = False
            for lid in lights:
                if lid in self._held_lights:
                    del self._held_lights[lid]
                    removed = True
        if removed:
            self._schedule_save()

    def clear_holds(self, keep_detected: bool = False) -> None:
        """Drop holds, so a phase entry starts from a clean default.

        With ``keep_detected=True`` the holds that record a *foreign*
        intervention (``"detected"`` — a scene, a manual dim) are preserved:
        they are the user's own doing, not a phase-scoped automation state,
        and survive the phase change until explicitly released. Service holds
        (``turn_on``/``turn_off`` with ``hold: true``) always end here, because
        they belong to the phase they were set in.
        """
        if keep_detected:
            before = len(self._held_lights)
            self._held_lights = {
                lid: reason
                for lid, reason in self._held_lights.items()
                if reason == HOLD_REASON_DETECTED
            }
            if len(self._held_lights) != before:
                self._schedule_save()
            return
        self.release_hold()

    def get_held_lights(self) -> set[str]:
        """Return a copy of the currently held lights."""
        return set(self._held_lights)

    def is_held(self, entity_id: str) -> bool:
        """True if *entity_id* is currently held."""
        return entity_id in self._held_lights

    def get_hold_reason(self, entity_id: str) -> str | None:
        """The reason *entity_id* is held, or None if it is not held."""
        return self._held_lights.get(entity_id)

    def get_hold_count(self) -> int:
        """Number of currently held lights."""
        return len(self._held_lights)

    def get_held_lights_with_reasons(self) -> dict[str, str]:
        """Return a copy of ``{light: reason}`` for the currently held lights."""
        return dict(self._held_lights)

    # ------------------------------------------------------------------
    #  Queries
    # ------------------------------------------------------------------

    def is_controlled_by_us(self, entity_id: str) -> bool:
        """True if we turned on / are controlling this light."""
        return entity_id in self._lights_we_control

    def get_lights_we_control(self) -> set[str]:
        """Return a copy of all lights we currently control."""
        return set(self._lights_we_control)

    # ------------------------------------------------------------------
    #  Bulk operations
    # ------------------------------------------------------------------

    def clear(self) -> None:
        """Clear all state (e.g. switch turned off)."""
        self._lights_we_control.clear()
        self._held_lights.clear()
        self._schedule_save()

    def prune(self, valid_lights: list[str]) -> None:
        """Remove entity_ids that are no longer in the configured lights list."""
        valid = set(valid_lights)
        before = len(self._lights_we_control)
        self._lights_we_control &= valid
        self._held_lights = {
            lid: reason for lid, reason in self._held_lights.items() if lid in valid
        }
        if len(self._lights_we_control) < before:
            _LOGGER.debug(
                "[%s] State pruned: removed %d stale entity_ids",
                self._instance_name,
                before - len(self._lights_we_control),
            )
            self._schedule_save()

    # ------------------------------------------------------------------
    #  LUX calibration
    # ------------------------------------------------------------------

    def set_lux_calibration(self, lux_at_100: float) -> None:
        """Store LUX calibration value (lamp contribution at 100% brightness)."""
        self._lux_calibration = lux_at_100
        self._schedule_save()
        _LOGGER.debug(
            "[%s] LUX calibration saved: %.1f lux at 100%%",
            self._instance_name,
            lux_at_100,
        )

    def get_lux_calibration(self) -> float | None:
        """Return stored LUX calibration value, or None if not calibrated."""
        return self._lux_calibration

    # ------------------------------------------------------------------
    #  Expected state (for external control detection)
    # ------------------------------------------------------------------

    def set_expected_state(
        self,
        light_id: str,
        on: bool,
        brightness_pct: int | None = None,
        kelvin: int | None = None,
    ) -> None:
        """Record expected state for a light when we apply values.

        This is persisted across reboots so external control detection
        knows what values to expect even after HA restart.

        Args:
            light_id: Entity ID of the light
            on: Whether light should be on or off
            brightness_pct: Expected brightness (None if not controlling)
            kelvin: Expected color temperature (None if not controlling)
        """
        import time
        self._expected_states[light_id] = {
            "on": on,
            "brightness_pct": brightness_pct,
            "kelvin": kelvin,
            "timestamp": time.time(),
        }
        self._schedule_save()
        _LOGGER.debug(
            "[%s] Expected state saved for %s: on=%s, brightness=%s, kelvin=%s",
            self._instance_name,
            light_id,
            on,
            brightness_pct if brightness_pct is not None else "N/A",
            kelvin if kelvin is not None else "N/A",
        )

    def get_expected_state(self, light_id: str) -> dict[str, Any] | None:
        """Get expected state for a light, or None if not recorded.

        Returns dict with keys: on, brightness_pct, kelvin, timestamp
        """
        return self._expected_states.get(light_id)

    def clear_expected_state(self, light_id: str) -> None:
        """Clear expected state for a light.

        Called when light is removed from config.
        """
        if light_id in self._expected_states:
            del self._expected_states[light_id]
            self._schedule_save()

    def prune_expected_states(self, valid_lights: list[str]) -> None:
        """Remove expected states for lights no longer in config."""
        valid = set(valid_lights)
        stale = set(self._expected_states.keys()) - valid
        if stale:
            for lid in stale:
                del self._expected_states[lid]
            self._schedule_save()

    def get_all_expected_states(self) -> dict[str, dict[str, Any]]:
        """Return all expected states (for mode transitions)."""
        return dict(self._expected_states)
