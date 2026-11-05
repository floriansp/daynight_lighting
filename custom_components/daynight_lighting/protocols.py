"""Protocol definitions for DayNight Lighting.

This module defines the interfaces between the main switch and its
collaborators, enabling dependency inversion and testability.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from .manual_control import ExpectedState

__all__ = [
    "ColorProvider",
    "InstanceController",
    "ModeProvider",
]


@runtime_checkable
class ColorProvider(Protocol):
    """Protocol for components that provide color temperature."""

    def is_enabled(self) -> bool:
        """Return True if color control is enabled."""
        ...

    def get_kelvin(self) -> tuple[int, float | None]:
        """Return color temperature in Kelvin and optional metadata.

        Returns:
            Tuple of (kelvin, metadata). Metadata may be sun elevation
            or None depending on implementation.
        """
        ...

    def get_expected_night_kelvin(self) -> int | None:
        """Return color temperature for night mode, or None if disabled."""
        ...


@runtime_checkable
class ModeProvider(Protocol):
    """Protocol for mode determination."""

    def get_current_mode(self) -> str:
        """Return current mode identifier.

        Returns:
            One of: MODE_DAY, MODE_NIGHT, MODE_SLEEP, MODE_WAKEUP
        """
        ...

    def is_day_mode(self) -> bool:
        """Check if currently in day mode (LUX-based control).

        Returns True for day mode, False for night mode.
        Note: sleep and wake-up modes are handled separately via
        get_current_mode().
        """
        ...


class InstanceController(Protocol):
    """What the other platforms and the services may ask of an instance.

    The main switch implements this. Entities and services reach it through
    ``hass.data`` and used to see an untyped object, so a private attribute
    of the switch could be reached without anyone noticing the coupling. This
    is the whole public surface they are allowed to use.
    """

    # --- state for the monitor entities ---------------------------------
    def get_active_mode(self) -> str | None: ...
    def get_mode_progress(self) -> float | None: ...
    def get_last_applied_target(self) -> ExpectedState | None: ...
    def get_held_lights(self) -> set[str]: ...
    def get_held_lights_with_reasons(self) -> dict[str, str]: ...
    def get_controlled_lights(self) -> list[str]: ...
    def get_discovery_info(self) -> dict[str, Any]: ...
    def get_motion_sensor_entities(self) -> list[str]: ...
    def get_active_motion_sensors(self) -> list[str]: ...
    def get_motion_now(self) -> bool: ...
    def get_lux_reading(self) -> dict[str, Any]: ...
    def has_motion_sensor(self) -> bool: ...
    def has_lux_sensor(self) -> bool: ...
    def has_dialled_brightness(self) -> bool: ...
    def is_wall_buttons_blocked(self) -> bool: ...
    def notify_monitors(self) -> None: ...

    # --- commands from buttons, numbers and services --------------------
    def release_hold(self) -> None: ...
    def hold_all_lights(self) -> None: ...
    def reset_brightness(self) -> None: ...
    def reapply_dialled_brightness(self) -> None: ...
    def adjust_brightness(self, step: int) -> str: ...
    def async_options_changed(self) -> None: ...

    # --- wall-button services -------------------------------------------
    def get_desired_turn_on_params(self, *, force_on: bool = False) -> dict[str, Any]: ...
    def prepare_lights_applied_by_service(
        self,
        lights: list[str],
        *,
        on: bool,
        brightness_pct: int | None = None,
        kelvin: int | None = None,
    ) -> None: ...
    def prepare_lights_turn_off_by_service(self, lights: list[str]) -> None: ...
    def record_lights_turned_on_by_service(
        self, lights: list[str], hold: bool = True
    ) -> None: ...
    def record_lights_turned_off_by_service(
        self, lights: list[str], hold: bool = True
    ) -> None: ...

    # --- sleep / wake-up services ---------------------------------------
    def start_sleep_mode_now(
        self,
        duration_min: int | None = None,
        brightness_pct: int | None = None,
        color_temp_kelvin: int | None = None,
    ) -> None: ...
    def start_wakeup_mode_now(
        self,
        duration_min: int | None = None,
        start_brightness_pct: int | None = None,
        end_brightness_pct: int | None = None,
        color_temp_kelvin: int | None = None,
    ) -> None: ...
    def stop_sleep_mode_now(self) -> None: ...
    def stop_wakeup_mode_now(self) -> None: ...

    # --- LUX calibration service ----------------------------------------
    def read_raw_lux(self) -> float | None: ...
    def store_lux_calibration(self, lamp_contribution_lux: float) -> None: ...
