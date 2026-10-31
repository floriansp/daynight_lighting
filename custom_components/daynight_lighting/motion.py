"""Motion controller for DayNight Lighting: motion sensor + night off-timer."""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import TYPE_CHECKING, Any, Callable

from homeassistant.core import HomeAssistant, callback
from homeassistant.util import dt as dt_util

from .config import NightModeConfig
from .parsing import is_motion_state_on

if TYPE_CHECKING:
    from .action_scheduler import ActionScheduler

_LOGGER = logging.getLogger(__name__)


class MotionController:
    """Handles motion sensor entities and night-mode off timer."""

    def __init__(
        self,
        hass: HomeAssistant,
        config: NightModeConfig,
        instance_name: str,
        motion_sensor_entity_id: str | list[str] | None = None,
        action_scheduler: ActionScheduler | None = None,
        cancel_key: str | None = None,
        get_transition: Callable[[str], int] | None = None,
    ) -> None:
        self._hass = hass
        self._config = config
        self._instance_name = instance_name
        # Normalize to list for multi-sensor support
        if motion_sensor_entity_id is None:
            self._motion_sensor_entity_ids: list[str] = []
        elif isinstance(motion_sensor_entity_id, str):
            self._motion_sensor_entity_ids = [motion_sensor_entity_id]
        else:
            self._motion_sensor_entity_ids = list(motion_sensor_entity_id)
        self._action_scheduler = action_scheduler
        self._cancel_key = cancel_key
        self._get_transition = get_transition
        self._motion_off_timer: asyncio.TimerHandle | None = None

    def get_motion_sensor_entity(self) -> str | None:
        """Primary motion sensor entity_id (for backward compatibility).

        Returns the first sensor if multiple are configured.
        """
        return self._motion_sensor_entity_ids[0] if self._motion_sensor_entity_ids else None

    def get_motion_sensor_entities(self) -> list[str]:
        """All configured motion sensor entity IDs."""
        return self._motion_sensor_entity_ids.copy()

    def has_motion_now(self) -> bool:
        """True if ANY motion/presence sensor is currently on (OR logic).

        With multiple sensors in an area, lights stay on if ANY sensor
        detects motion, providing seamless coverage across the space.
        """
        if not self._motion_sensor_entity_ids:
            return False

        for entity_id in self._motion_sensor_entity_ids:
            state = self._hass.states.get(entity_id)
            if is_motion_state_on(state):
                return True
        return False

    def get_active_motion_sensors(self) -> list[str]:
        """Return list of motion sensors that are currently active (on).

        Useful for debugging and logging which specific sensors triggered.
        """
        active = []
        for entity_id in self._motion_sensor_entity_ids:
            state = self._hass.states.get(entity_id)
            if is_motion_state_on(state):
                active.append(entity_id)
        return active

    def schedule_night_motion_off(
        self,
        lights: list[str],
        callback_fn: Callable[[], tuple[list[str], str | None]],
    ) -> None:
        """Schedule turn_off after motion_off_delay. callback_fn() returns (entity_ids to turn off, skip_reason or None). Scheduler (or fallback) performs turn_off and logging."""
        self.cancel_night_motion_off_timer()
        if not lights:
            return

        delay_min = self._config.motion_off_delay_min

        if self._action_scheduler is not None and self._cancel_key is not None:
            run_at = dt_util.utcnow() + timedelta(minutes=delay_min)
            self._action_scheduler.add(
                run_at,
                self._cancel_key,
                source="MotionController",
                lights_for_log=lights,
                callback_fn=callback_fn,
                reason="motion_off",
            )
            return

        delay_sec = delay_min * 60

        @callback
        def _turn_off_lights() -> None:
            self._motion_off_timer = None
            entity_ids, skip_reason = callback_fn()
            if skip_reason:
                _LOGGER.debug(
                    "[%s] ActionScheduler (fallback): source=MotionController (motion_off) not turning off — %s",
                    self._instance_name,
                    skip_reason,
                )
            elif entity_ids:
                # Apply transition when turning off lights
                off_payload: dict[str, Any] = {"entity_id": entity_ids}
                if self._get_transition is not None:
                    transition_sec = self._get_transition("initial")
                    if transition_sec > 0:
                        off_payload["transition"] = transition_sec
                self._hass.async_create_task(
                    self._hass.services.async_call(
                        "light", "turn_off", off_payload
                    )
                )
                _LOGGER.debug(
                    "[%s] ActionScheduler (fallback): source=MotionController (motion_off) turn_off lights=%s",
                    self._instance_name,
                    entity_ids,
                )
            else:
                _LOGGER.debug(
                    "[%s] ActionScheduler (fallback): source=MotionController (motion_off) turn_off (none)",
                    self._instance_name,
                )

        self._motion_off_timer = self._hass.loop.call_later(
            delay_sec, _turn_off_lights
        )

    def cancel_night_motion_off_timer(self) -> None:
        """Cancel any scheduled night-mode turn_off."""
        if self._action_scheduler is not None and self._cancel_key is not None:
            self._action_scheduler.remove(self._cancel_key)
            return
        if self._motion_off_timer is not None:
            self._motion_off_timer.cancel()
            self._motion_off_timer = None

