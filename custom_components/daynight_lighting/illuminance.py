"""Illuminance (LUX) sensor reader for DayNight Lighting."""

from __future__ import annotations

from collections import deque
from datetime import datetime, timedelta
import logging
import time

from homeassistant.core import HomeAssistant

from .config import IlluminanceConfig
from .parsing import calculate_compensated_lux, parse_lux_state

_LOGGER = logging.getLogger(__name__)


class IlluminanceReader:
    """Reads LUX from configured light sensor entities (supports multiple sensors).

    **Multi-sensor support:**
    - Averages readings from multiple illuminance sensors in an area
    - Falls back to available sensors if some are unavailable

    **Anti-flapping features:**
    - **LUX smoothing:** Rolling average over N samples to reduce noise.
    - **Brightness change threshold:** Only returns a new brightness if it
      differs from the last *applied* brightness by at least X%.
    - **Flapping detection:** Tracks direction changes and freezes brightness
      if oscillation is detected.
    - **LUX compensation:** Optional calibration to subtract the contribution
      of our own lights from the sensor reading.
    """

    # How many applied-brightness samples to remember for flapping detection.
    # The flapping check looks back five minutes; a feedback loop (the LUX
    # sensor reacting to its own lamps) oscillates over *minutes*, so the
    # history must hold a full cycle. The old window of five samples only
    # caught fast oscillation and let slow loops (e.g. 28% → 3% → 28% over
    # five minutes) keep swinging indefinitely.
    FLAPPING_HISTORY_MAXLEN = 60

    def __init__(
        self,
        hass: HomeAssistant,
        config: IlluminanceConfig,
        instance_name: str,
        light_sensor_entity_id: str | list[str] | None = None,
    ) -> None:
        self._hass = hass
        self._config = config
        self._instance_name = instance_name
        # Normalize to list for multi-sensor support
        if light_sensor_entity_id is None:
            self._light_sensor_entity_ids: list[str] = []
        elif isinstance(light_sensor_entity_id, str):
            self._light_sensor_entity_ids = [light_sensor_entity_id]
        else:
            self._light_sensor_entity_ids = list(light_sensor_entity_id)

        # Log the configured sensors for debugging
        _LOGGER.info(
            "[%s] IlluminanceReader initialized with sensors: %s",
            self._instance_name,
            self._light_sensor_entity_ids,
        )

        # LUX smoothing (rolling average)
        self._lux_samples: deque[float] = deque(maxlen=max(1, config.smoothing_samples))

        # Brightness change threshold & flapping detection
        self._last_applied_brightness_pct: int | None = None
        self._brightness_history: deque[tuple[datetime, int]] = deque(
            maxlen=self.FLAPPING_HISTORY_MAXLEN
        )
        self._flapping_freeze_until: datetime | None = None

        # LUX compensation (calibration data loaded separately)
        self._lux_lamp_contribution_at_100: float | None = None

        # Track recently logged sensors to avoid duplicate logging within same tick
        self._last_logged_values: dict[str, tuple[float, float]] = {}
        self._log_dedup_window: float = 0.5  # seconds
        # "No light_sensor configured" is emitted once per instance lifetime:
        # the monitor sensors read LUX many times per tick, and the message is
        # only useful as a one-off notice, not as a per-call flood.
        self._no_sensor_logged = False

    # ------------------------------------------------------------------
    #  LUX calibration (compensation)
    # ------------------------------------------------------------------

    def set_lux_calibration(self, lux_at_100: float | None) -> None:
        """Set the calibrated LUX contribution of our lights at 100% brightness.

        This value is used to estimate and subtract the lamp contribution from
        the raw sensor reading, isolating the ambient (daylight) component.
        """
        self._lux_lamp_contribution_at_100 = lux_at_100
        if lux_at_100 is not None:
            _LOGGER.info(
                "[%s] LUX calibration loaded: %.1f lux at 100%% brightness",
                self._instance_name,
                lux_at_100,
            )

    def get_lux_calibration(self) -> float | None:
        """Return the calibrated LUX contribution at 100%, or None if not calibrated."""
        return self._lux_lamp_contribution_at_100

    # ------------------------------------------------------------------
    #  Core LUX reading
    # ------------------------------------------------------------------

    def get_light_sensor_entity(self) -> str | None:
        """Primary light sensor entity_id (for backward compatibility).

        Returns the first sensor if multiple are configured.
        """
        return self._light_sensor_entity_ids[0] if self._light_sensor_entity_ids else None

    def get_light_sensor_entities(self) -> list[str]:
        """All configured light sensor entity IDs."""
        return self._light_sensor_entity_ids.copy()

    def _get_all_lux_raw(self) -> list[float]:
        """Get raw LUX readings from all configured sensors.

        Returns a list of valid LUX values from all available sensors.
        Unavailable or invalid sensors are skipped.
        """
        values = []
        now = time.monotonic()
        for entity_id in self._light_sensor_entity_ids:
            state = self._hass.states.get(entity_id)
            if state is None:
                # Only log if we haven't logged this recently
                last_log = self._last_logged_values.get(entity_id)
                if last_log is None or (now - last_log[0]) >= self._log_dedup_window:
                    _LOGGER.debug(
                        "[%s] Light sensor %s has no state (entity not found)",
                        self._instance_name,
                        entity_id,
                    )
                    self._last_logged_values[entity_id] = (now, -1)
                continue
            lux = parse_lux_state(state)
            if lux is not None:
                # Only log if value changed or enough time passed
                last_log = self._last_logged_values.get(entity_id)
                if last_log is None or (now - last_log[0]) >= self._log_dedup_window or abs(last_log[1] - lux) >= 0.1:
                    _LOGGER.debug(
                        "[%s] Light sensor %s = %.1f lux",
                        self._instance_name,
                        entity_id,
                        lux,
                    )
                    self._last_logged_values[entity_id] = (now, lux)
                values.append(lux)
            else:
                # Only log if we haven't logged this recently
                last_log = self._last_logged_values.get(entity_id)
                if last_log is None or (now - last_log[0]) >= self._log_dedup_window:
                    _LOGGER.debug(
                        "[%s] Light sensor %s state not numeric: %s",
                        self._instance_name,
                        entity_id,
                        state.state,
                    )
                    self._last_logged_values[entity_id] = (now, -1)
        return values

    def get_lux_raw(self) -> float | None:
        """Current LUX from light sensors (raw, no smoothing); None if unavailable.

        With multiple sensors, returns the average of all available readings.
        """
        if not self._light_sensor_entity_ids:
            if not self._no_sensor_logged:
                _LOGGER.debug("[%s] No light_sensor configured", self._instance_name)
                self._no_sensor_logged = True
            return None

        values = self._get_all_lux_raw()
        if not values:
            return None

        # Return average of all sensors
        return sum(values) / len(values)

    def get_lux(self) -> float | None:
        """Current LUX with smoothing and compensation applied.

        Returns the rolling average of the last N samples (where N is
        configured via ``lux_smoothing_samples``). If calibration data is
        available, the estimated lamp contribution is subtracted from the
        raw reading before smoothing.
        """
        lux_raw = self.get_lux_raw()
        if lux_raw is None:
            return None

        # Apply compensation if calibrated
        lux_compensated = self._apply_lux_compensation(lux_raw)

        # Add to rolling average buffer
        self._lux_samples.append(lux_compensated)

        # Return average
        return sum(self._lux_samples) / len(self._lux_samples)

    def _apply_lux_compensation(self, lux_measured: float) -> float:
        """Subtract estimated lamp contribution from the measured LUX.

        If no calibration data is available, returns the measured value unchanged.
        The lamp contribution is estimated linearly based on the last applied
        brightness percentage.
        """
        ambient_lux = calculate_compensated_lux(
            lux_measured,
            self._lux_lamp_contribution_at_100,
            self._last_applied_brightness_pct,
        )

        # Log if compensation was applied
        if self._lux_lamp_contribution_at_100 is not None and self._last_applied_brightness_pct is not None:
            lamp_lux = self._lux_lamp_contribution_at_100 * (
                self._last_applied_brightness_pct / 100.0
            )
            _LOGGER.debug(
                "[%s] LUX compensation: measured=%.1f, lamp_contrib=%.1f (at %d%%),"
                " ambient=%.1f",
                self._instance_name,
                lux_measured,
                lamp_lux,
                self._last_applied_brightness_pct,
                ambient_lux,
            )

        return ambient_lux

    # ------------------------------------------------------------------
    #  Anti-flapping: brightness threshold & flapping detection
    # ------------------------------------------------------------------

    def should_apply_brightness(self, brightness_pct: int) -> bool:
        """Check if *brightness_pct* should be applied based on threshold & flapping.

        Returns ``True`` if the brightness differs from the last applied value
        by at least the configured threshold **and** we are not currently in a
        flapping freeze period.

        Call :meth:`record_brightness_applied` after successfully sending the
        new brightness to update the internal state.
        """
        now = datetime.now()

        # Check flapping freeze
        if self._flapping_freeze_until is not None:
            if now < self._flapping_freeze_until:
                _LOGGER.debug(
                    "[%s] Flapping freeze active (until %s), skipping brightness %d%%",
                    self._instance_name,
                    self._flapping_freeze_until.strftime("%H:%M:%S"),
                    brightness_pct,
                )
                return False
            # Freeze expired
            self._flapping_freeze_until = None
            _LOGGER.debug(
                "[%s] Flapping freeze expired, resuming brightness control",
                self._instance_name,
            )

        # Check threshold
        if self._last_applied_brightness_pct is not None:
            threshold_pct = self._config.brightness_change_threshold_pct
            diff = abs(brightness_pct - self._last_applied_brightness_pct)
            if diff < threshold_pct:
                _LOGGER.debug(
                    "[%s] Brightness change %d%% → %d%% (Δ=%d%%) below"
                    " threshold (%d%%), skipping",
                    self._instance_name,
                    self._last_applied_brightness_pct,
                    brightness_pct,
                    diff,
                    threshold_pct,
                )
                return False

        return True

    def get_last_applied_brightness(self) -> int | None:
        """The last brightness we actually sent, None if none was sent yet.

        This is the damping reference: a freshly computed brightness is only
        sent when it differs from this by the threshold. Callers that report
        the current target need this value, not the just-computed one, when
        the damper decided not to send anything.
        """
        return self._last_applied_brightness_pct

    def forget_applied_brightness(self) -> None:
        """Drop the damping reference so the next brightness is not skipped.

        The flapping freeze is deliberately kept: a room that was oscillating
        is still oscillating after somebody else touched its lights, and
        clearing the freeze would let it resume immediately.
        """
        if self._last_applied_brightness_pct is None and not self._brightness_history:
            return
        _LOGGER.debug(
            "[%s] Forgetting last applied brightness (%s%%)",
            self._instance_name,
            self._last_applied_brightness_pct,
        )
        self._last_applied_brightness_pct = None
        self._brightness_history.clear()

    def record_brightness_applied(self, brightness_pct: int) -> None:
        """Record that *brightness_pct* was successfully applied.

        Updates the last applied brightness and checks for flapping
        (direction oscillation). If flapping is detected, starts a freeze
        period to prevent further adjustments.
        """
        now = datetime.now()
        self._last_applied_brightness_pct = brightness_pct
        self._brightness_history.append((now, brightness_pct))

        # Flapping detection: check if direction changed 3+ times in the last 5 minutes
        if len(self._brightness_history) >= 4:
            self._check_flapping()

    def _check_flapping(self) -> None:
        """Detect oscillation (flapping) in brightness changes.

        If the direction (up/down) changes 3+ times within 5 minutes, we
        consider it flapping and freeze brightness adjustments for a
        configurable period.
        """
        now = datetime.now()
        recent = [
            (ts, pct)
            for ts, pct in self._brightness_history
            if (now - ts).total_seconds() < 300  # 5 minutes
        ]
        if len(recent) < 4:
            return

        # Compute direction changes: +1 for up, -1 for down
        directions: list[int] = []
        for i in range(1, len(recent)):
            prev_pct = recent[i - 1][1]
            curr_pct = recent[i][1]
            if curr_pct > prev_pct:
                directions.append(1)
            elif curr_pct < prev_pct:
                directions.append(-1)

        # Count direction changes
        changes = sum(
            1 for i in range(1, len(directions)) if directions[i] != directions[i - 1]
        )

        if changes >= 3:
            freeze_min = self._config.flapping_freeze_min
            self._flapping_freeze_until = now + timedelta(minutes=freeze_min)
            _LOGGER.warning(
                "[%s] Flapping detected (%d direction changes in 5 min),"
                " freezing brightness for %d minutes",
                self._instance_name,
                changes,
                freeze_min,
            )

    def clear_state(self) -> None:
        """Clear all anti-flapping state (e.g. when integration is turned off or reset)."""
        self._lux_samples.clear()
        self._last_applied_brightness_pct = None
        self._brightness_history.clear()
        self._flapping_freeze_until = None
        self._last_logged_values.clear()
