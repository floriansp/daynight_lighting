"""Action scheduler for DayNight Lighting: run turn_off (or other actions) at a given time, cancel by key."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import datetime
from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.util import dt as dt_util

_LOGGER = logging.getLogger(__name__)


def _source_label(source: str, reason: str | None) -> str:
    """Build log label: controller name and optional reason (e.g. 'MotionController (motion_off)')."""
    if reason:
        return f"{source} ({reason})"
    return source


class ActionScheduler:
    """
    Schedules turn_off (or similar) to run at a given time.
    source = controller that requested the action (e.g. MotionController); reason = optional cause (e.g. motion_off).
    Callback returns (entity_ids to turn off, skip_reason or None); scheduler executes turn_off and logs.
    Entries can be removed by cancel_key before they run.
    """

    def __init__(self, hass: HomeAssistant, instance_name: str = "") -> None:
        self._hass = hass
        self._instance_name = instance_name
        self._entries: list[dict[str, Any]] = []
        self._timer: asyncio.TimerHandle | None = None

    def add(
        self,
        run_at: datetime,
        cancel_key: str,
        source: str,
        lights_for_log: list[str],
        callback_fn: Callable[[], tuple[list[str], str | None]],
        reason: str | None = None,
    ) -> None:
        """Schedule a turn_off at run_at. source = requesting controller (e.g. MotionController), reason = optional (e.g. motion_off). callback returns (entity_ids, skip_reason)."""
        self._entries.append({
            "run_at": run_at,
            "cancel_key": cancel_key,
            "source": source,
            "reason": reason,
            "callback": callback_fn,
        })
        now = dt_util.utcnow()
        delay_sec = max(0, (run_at - now).total_seconds())
        delay_min = round(delay_sec / 60)
        label = _source_label(source, reason)
        _LOGGER.debug(
            "[%s] ActionScheduler: scheduled turn_off in %s min, source=%s, lights=%s",
            self._instance_name or "scheduler",
            delay_min,
            label,
            lights_for_log,
        )
        self._schedule_next()

    def remove(self, cancel_key: str) -> None:
        """Remove all scheduled entries with this cancel_key."""
        before = len(self._entries)
        self._entries = [e for e in self._entries if e["cancel_key"] != cancel_key]
        if len(self._entries) < before:
            _LOGGER.debug(
                "[%s] ActionScheduler: removed %s entry/entries for key %s",
                self._instance_name or "scheduler",
                before - len(self._entries),
                cancel_key[:8] + "…" if len(cancel_key) > 8 else cancel_key,
            )
        self._schedule_next()

    def _schedule_next(self) -> None:
        """Cancel current timer and set one for the earliest run_at, if any."""
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None

        if not self._entries:
            return

        now = dt_util.utcnow()
        earliest = min(e["run_at"] for e in self._entries)
        delay_sec = (earliest - now).total_seconds()
        if delay_sec <= 0:
            self._run_due()
            return

        @callback
        def _on_timer() -> None:
            self._timer = None
            self._run_due()

        self._timer = self._hass.loop.call_later(delay_sec, _on_timer)

    def _run_due(self) -> None:
        """Run all due entries: callback returns (entity_ids, reason); scheduler does turn_off and logs."""
        now = dt_util.utcnow()
        due = [e for e in self._entries if e["run_at"] <= now]
        self._entries = [e for e in self._entries if e["run_at"] > now]
        prefix = self._instance_name or "scheduler"
        for e in due:
            try:
                entity_ids, skip_reason = e["callback"]()
                label = _source_label(e.get("source", "?"), e.get("reason"))
                if skip_reason:
                    _LOGGER.debug(
                        "[%s] ActionScheduler: source=%s not turning off — %s",
                        prefix,
                        label,
                        skip_reason,
                    )
                elif entity_ids:
                    self._hass.async_create_task(
                        self._hass.services.async_call(
                            "light",
                            "turn_off",
                            {"entity_id": entity_ids},
                        )
                    )
                    _LOGGER.debug(
                        "[%s] ActionScheduler: source=%s turn_off lights=%s",
                        prefix,
                        label,
                        entity_ids,
                    )
                else:
                    _LOGGER.debug(
                        "[%s] ActionScheduler: source=%s turn_off (none)",
                        prefix,
                        label,
                    )
            except Exception:  # noqa: BLE001
                _LOGGER.exception(
                    "[%s] ActionScheduler: callback failed for source %s",
                    prefix,
                    _source_label(e.get("source", "?"), e.get("reason")),
                )
        self._schedule_next()
