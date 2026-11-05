"""Switch platform for DayNight Lighting.

Contains the main orchestration switch, **DayNightLightingSwitch**, which
delegates to the mode handlers. The three auxiliary switches live in
``control_switches`` and are set up here as well.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_ON
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event, async_track_time_change
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.util import dt as dt_util

from .action_scheduler import ActionScheduler
from .brightness_dials import BrightnessDials
from .circadian import CircadianController
from .config import DayNightConfig
from .const import (
    CONF_AREA_ID,
    CONF_INITIAL_TRANSITION_SECONDS,
    CONF_INSTANCE_NAME,
    CONF_MODE_TRANSITION_SECONDS,
    CONF_TRANSITION_SECONDS,
    CONF_WAKEUP_DURATION_MIN,
    DAY_FALLBACK_CIRCADIAN_ONLY,
    DAY_FALLBACK_FIXED,
    DAY_FALLBACK_SKIP,
    DEFAULT_INITIAL_TRANSITION_SECONDS,
    DEFAULT_MODE_TRANSITION_SECONDS,
    DEFAULT_TRANSITION_SECONDS,
    DEFAULT_WAKEUP_DURATION_MIN,
    DOMAIN,
    EVENT_MODE_CHANGED,
    MAX_TICK_TRANSITION_SECONDS,
    MIN_DIAL_BRIGHTNESS_PCT,
    MODE_DAY,
    MODE_NIGHT,
    MODE_SLEEP,
    MODE_WAKEUP,
    SIGNAL_MONITOR_UPDATE,
)
from .context import SharedHandlerDeps
from .control_switches import (
    DayNightLightingBlockWallButtonsSwitch,
    DayNightLightingControlBrightnessSwitch,
    DayNightLightingControlColorSwitch,
)
from .handlers import (
    DayModeHandler,
    ModeHandler,
    ModeHandlers,
    NightModeHandler,
    SleepModeHandler,
    WakeUpModeHandler,
)
from .expectation_adoption import ExpectationAdopter
from .external_control import ExternalControlMonitor
from .hold_validation import RestoredHoldValidator
from .illuminance import IlluminanceReader
from .instance_discovery import InstanceDiscovery
from .instance_data import (
    KEY_BLOCK_WALL_BUTTONS,
    KEY_CONTROL_BRIGHTNESS,
    KEY_CONTROL_COLOR,
    KEY_MAIN_SWITCH,
    instance_entity,
    is_entity_on,
)
from .lights import LightsController
from .manual_control import (
    DetectionPolicy,
    ExpectedState,
    ManualControlDetector,
)
from .motion import MotionController
from .parsing import calculate_compensated_lux
from .protocols import ModeProvider
from .mode_schedule import DayNightSchedule
from .state_controller import (
    HOLD_REASON_SERVICE,
    StateController,
)
from .transition_coordinator import TransitionCoordinator
from .weather import WeatherReader

__all__ = [
    "DayNightLightingSwitch",
    "DayNightLightingControlBrightnessSwitch",
    "DayNightLightingControlColorSwitch",
]

_LOGGER = logging.getLogger(__name__)

# Quiet-period before a registry event stream is acted on. HA fires one
# entity/device/area registry event per restored item at startup, so hundreds
# of events arrive within seconds; running the area scan per event floods the
# log and re-iterates every registry pointlessly. The scan is debounced: it
# runs once the event stream pauses, so a newly added lamp is still adopted
# within seconds while the startup burst collapses into a single pass.
REGISTRY_DEBOUNCE_SECONDS = 5

# Registry-update event names. These used to live in ``homeassistant.const``
# but were moved to the registry helper modules (as typed ``EventType``
# objects) in HA 2025/2026. The bus still accepts the plain, stable strings,
# so we hard-code them instead of importing a constant that keeps moving.
EVENT_ENTITY_REGISTRY_UPDATED = "entity_registry_updated"
EVENT_DEVICE_REGISTRY_UPDATED = "device_registry_updated"
EVENT_AREA_REGISTRY_UPDATED = "area_registry_updated"


# -------------------------------------------------------------------
#  Platform setup
# -------------------------------------------------------------------

async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up DayNight Lighting switches from a config entry."""
    name = (
        config_entry.data.get(CONF_INSTANCE_NAME)
        or config_entry.options.get(CONF_INSTANCE_NAME)
        or "DayNight"
    )
    data = hass.data.setdefault(DOMAIN, {}).setdefault(config_entry.entry_id, {})

    control_brightness_switch = DayNightLightingControlBrightnessSwitch(config_entry)
    control_color_switch = DayNightLightingControlColorSwitch(config_entry)
    block_wall_buttons_switch = DayNightLightingBlockWallButtonsSwitch(config_entry)
    data[KEY_CONTROL_BRIGHTNESS] = control_brightness_switch
    data[KEY_CONTROL_COLOR] = control_color_switch
    data[KEY_BLOCK_WALL_BUTTONS] = block_wall_buttons_switch

    main_switch = DayNightLightingSwitch(config_entry, name)
    data[KEY_MAIN_SWITCH] = main_switch

    async_add_entities(
        [
            main_switch,
            control_brightness_switch,
            control_color_switch,
            block_wall_buttons_switch,
        ]
    )


# ===================================================================
#  Main switch – orchestrates day (LUX) and night (motion) control
# ===================================================================

class DayNightLightingSwitch(SwitchEntity, RestoreEntity):
    """DayNight Lighting instance - orchestrator using mode handlers.

    The switch builds its collaborators itself, lazily and from the current
    options, and drops them in ``_invalidate_option_caches`` when the options
    change. That is the one place the object graph is wired.
    """

    _attr_has_entity_name = True
    _attr_name = None

    def __init__(
        self,
        config_entry: ConfigEntry,
        name: str,
        *,
        mode_provider: ModeProvider | None = None,
    ) -> None:
        """Initialize the DayNight Lighting switch.

        Args:
            config_entry: Config entry of this instance
            name: Instance name for logging
            mode_provider: Replaces the schedule, e.g. to pin a mode in tests
        """
        self._config_entry = config_entry
        self._instance_name = name
        self._attr_unique_id = f"{config_entry.entry_id}-main"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, config_entry.entry_id)},
            name=f"DayNight Lighting {name}",
        )
        self._attr_is_on = False
        self._unsub: list[Any] = []
        self._last_mode: str | None = None
        self._last_applied_target: ExpectedState | None = None
        self._first_tick_after_startup: bool = False  # Skip external control detection on first tick

        self._schedule_override = mode_provider

        # Lazy-init helper instances, rebuilt from the options on demand
        self._illuminance_reader: IlluminanceReader | None = None
        self._motion_instance: MotionController | None = None
        self._lights_instance: LightsController | None = None
        self._circadian_instance: CircadianController | None = None
        self._manual_control_detector_instance: ManualControlDetector | None = None
        self._weather_instance: WeatherReader | None = None
        self._action_scheduler_instance: ActionScheduler | None = None
        self._state_ctrl_instance: StateController | None = None
        self._shared_deps_instance: SharedHandlerDeps | None = None
        self._mode_handlers_instance: ModeHandlers | None = None
        self._transition_coordinator_instance: TransitionCoordinator | None = None
        self._discovery_instance: InstanceDiscovery | None = None
        self._dials_instance: BrightnessDials | None = None
        self._restored_holds_instance: RestoredHoldValidator | None = None
        self._expectation_adopter_instance: ExpectationAdopter | None = None
        self._external_control_instance: ExternalControlMonitor | None = None
        # Pending debounced registry re-scan, see _on_registry_changed().
        self._registry_debounce: Any | None = None

    # ---------------------------------------------------------------
    #  Properties – options & entity
    # ---------------------------------------------------------------

    @property
    def _options(self) -> dict:
        return self._config_entry.options

    @property
    def _config(self) -> DayNightConfig:
        # Pass area_id from config_entry.data as fallback (stored there during initial setup)
        data_area_id = self._config_entry.data.get(CONF_AREA_ID)
        return DayNightConfig.from_ha_options(
            self._config_entry.options, data_area_id=data_area_id
        )

    @property
    def name(self) -> str:
        return "DayNight Lighting"

    @property
    def unique_id(self) -> str:
        return self._attr_unique_id

    @property
    def is_on(self) -> bool:
        return self._attr_is_on

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        cfg = self._config
        attrs: dict[str, Any] = {
            "lights": self._lights.get_lights_list(),
        }

        # Add area-based discovery info if enabled
        if cfg.is_area_based() and cfg.area_id:
            discovery = self._discovery.scan()
            attrs["area"] = discovery["area_name"]
            attrs["area_id"] = cfg.area_id

            # Show discovered vs included lights
            attrs["area_lights_total"] = len(discovery["lights_in_area"])
            attrs["area_lights_controlled"] = len(cfg.included_lights)

            # Show discovered sensors
            motion_sensors = discovery["motion_sensors"]
            attrs["motion_sensors_discovered"] = motion_sensors
            attrs["illuminance_sensors_discovered"] = discovery["illuminance_sensors"]
            if cfg.excluded_motion_sensors:
                attrs["motion_sensors_excluded"] = cfg.excluded_motion_sensors

            # Show active motion sensors
            if motion_sensors:
                active = [
                    s
                    for s in motion_sensors
                    if self.hass.states.get(s)
                    and self.hass.states.get(s).state == STATE_ON
                ]
                attrs["motion_sensors_active"] = active

        return attrs

    @callback
    def _on_registry_changed(self, _ev: Any) -> None:
        """Debounce registry events into a single re-discovery pass.

        HA fires one entity/device/area registry event per restored item at
        startup, so hundreds of events arrive within seconds. Running the
        area scan per event floods the log and re-iterates every registry
        pointlessly. Instead each event (re)arms a short quiet-period timer:
        the scan runs once the stream pauses, so a newly added lamp or sensor
        is still adopted within seconds while the startup burst collapses
        into a single pass.
        """
        if not self._attr_is_on:
            return
        if not self._discovery.is_area_based():
            return

        if self._registry_debounce is not None:
            self._registry_debounce.cancel()
        self._registry_debounce = self.hass.loop.call_later(
            REGISTRY_DEBOUNCE_SECONDS, self._apply_registry_change
        )

    @callback
    def _apply_registry_change(self) -> None:
        """Run the debounced re-discovery (see :meth:`_on_registry_changed`)."""
        self._registry_debounce = None
        if not self._discovery.adoption_changed():
            return

        _LOGGER.info(
            "[%s] Area entities changed (registry update), re-discovering",
            self._instance_name,
        )
        self._start_listeners()

    # ---------------------------------------------------------------
    #  Lazy-init helper properties
    # ---------------------------------------------------------------

    @property
    def _dials(self) -> BrightnessDials:
        """The brightness dials; they look their entities up on every use."""
        if self._dials_instance is None:
            self._dials_instance = BrightnessDials(self._entity)
        return self._dials_instance

    @property
    def _discovery(self) -> InstanceDiscovery:
        """Area discovery of this instance; reads the current options each time."""
        if self._discovery_instance is None:
            self._discovery_instance = InstanceDiscovery(
                self.hass, lambda: self._config, self._instance_name
            )
        return self._discovery_instance

    @property
    def _illuminance(self) -> IlluminanceReader:
        sensor_ids = self._discovery.resolve_sensor_ids("light_sensor")

        # Re-create reader if sensors changed (e.g., discovery found sensors after startup)
        current_sensors = set(sensor_ids)
        cached_sensors = set(self._illuminance_reader.get_light_sensor_entities() if self._illuminance_reader else [])

        if self._illuminance_reader is None or cached_sensors != current_sensors:
            _LOGGER.info(
                "[%s] Using %d illuminance sensor(s): %s",
                self._instance_name,
                len(sensor_ids),
                sensor_ids,
            )
            self._illuminance_reader = IlluminanceReader(
                self.hass,
                self._config.illuminance,
                self._instance_name,
                light_sensor_entity_id=sensor_ids,
            )
        return self._illuminance_reader

    @property
    def _schedule(self) -> ModeProvider:
        if self._schedule_override is not None:
            return self._schedule_override
        cfg = self._config
        return DayNightSchedule(
            self.hass,
            night_mode=cfg.night_mode,
            sleep_mode=cfg.sleep_mode,
            wakeup_mode=cfg.wake_up_mode,
        )

    @property
    def _action_scheduler(self) -> ActionScheduler:
        if self._action_scheduler_instance is None:
            self._action_scheduler_instance = ActionScheduler(
                self.hass, self._instance_name
            )
        return self._action_scheduler_instance

    @property
    def _motion(self) -> MotionController:
        sensor_ids = self._discovery.resolve_sensor_ids("motion_sensor")

        # Re-create controller if sensors changed (e.g., discovery found sensors after startup)
        current_sensors = set(sensor_ids)
        cached_sensors = set(self._motion_instance.get_motion_sensor_entities() if self._motion_instance else [])

        if self._motion_instance is None or cached_sensors != current_sensors:
            _LOGGER.info(
                "[%s] Using %d motion sensor(s): %s",
                self._instance_name,
                len(sensor_ids),
                sensor_ids,
            )
            self._motion_instance = MotionController(
                self.hass,
                self._config.night_mode,
                self._instance_name,
                motion_sensor_entity_id=sensor_ids,
                action_scheduler=self._action_scheduler,
                cancel_key=self._config_entry.entry_id,
                get_transition=self._get_transition,
            )
        return self._motion_instance

    @property
    def _lights(self) -> LightsController:
        if self._lights_instance is None:
            cfg = self._config
            # Use effective lights (handles both legacy and area-based modes);
            # with hass it also discovers the area lights when none are chosen.
            lights_list = cfg.get_effective_lights(self.hass)
            if cfg.is_area_based():
                _LOGGER.info(
                    "[%s] Area discovery: Using %d light(s): %s",
                    self._instance_name,
                    len(lights_list),
                    lights_list,
                )
            self._lights_instance = LightsController(
                self.hass, lights_list, self._instance_name
            )
        return self._lights_instance

    @property
    def _circadian(self) -> CircadianController:
        if self._circadian_instance is None:
            cfg = self._config
            self._circadian_instance = CircadianController(
                self.hass, cfg.circadian, self._instance_name
            )
        return self._circadian_instance

    @property
    def _weather(self) -> WeatherReader:
        if self._weather_instance is None:
            cfg = self._config
            self._weather_instance = WeatherReader(
                self.hass, cfg.weather, self._instance_name
            )
        return self._weather_instance

    @property
    def _manual_control_detector(self) -> ManualControlDetector:
        if self._manual_control_detector_instance is None:
            self._manual_control_detector_instance = ManualControlDetector(
                self._instance_name,
            )
        return self._manual_control_detector_instance

    @property
    def _state_ctrl(self) -> StateController:
        if self._state_ctrl_instance is None:
            self._state_ctrl_instance = StateController(
                self.hass,
                self._config_entry.entry_id,
                self._instance_name,
            )
        return self._state_ctrl_instance

    @property
    def _restored_holds(self) -> RestoredHoldValidator:
        """Validator of restored holds; survives option changes like the state.

        Its pending checks describe what was restored at load, so rebuilding
        it with the option caches would silently forget them.
        """
        if self._restored_holds_instance is None:
            self._restored_holds_instance = RestoredHoldValidator(
                self.hass,
                self._state_ctrl,
                self._detection_policy,
                self._instance_name,
            )
        return self._restored_holds_instance

    @property
    def _expectation_adopter(self) -> ExpectationAdopter:
        """Adopter of uncommanded lights; follows the detector it reports to."""
        if self._expectation_adopter_instance is None:
            self._expectation_adopter_instance = ExpectationAdopter(
                self.hass,
                self._state_ctrl,
                self._manual_control_detector.mark_applied,
                self._instance_name,
            )
        return self._expectation_adopter_instance

    @property
    def _external_control(self) -> ExternalControlMonitor:
        """Detector of foreign interventions; follows the detector it uses."""
        if self._external_control_instance is None:
            self._external_control_instance = ExternalControlMonitor(
                self.hass,
                self._state_ctrl,
                self._manual_control_detector,
                self._restored_holds,
                self._detection_policy,
                self._in_ramp,
                self._interrupt_ramps,
                lambda: self._first_tick_after_startup,
                self._instance_name,
            )
        return self._external_control_instance

    @property
    def _handlers(self) -> ModeHandlers:
        """Get mode handlers, recreating if invalidated."""
        if self._mode_handlers_instance is None:
            self._mode_handlers_instance = self._create_mode_handlers()
        return self._mode_handlers_instance

    def _get_mode_handler(self, mode: str | None) -> ModeHandler | None:
        """The handler routing by mode identifier; typed access is ``_handlers``."""
        return self._handlers.for_mode(mode)

    @property
    def _transition_coordinator(self) -> TransitionCoordinator:
        """Get transition coordinator, recreating if invalidated."""
        if self._transition_coordinator_instance is None:
            self._transition_coordinator_instance = self._create_transition_coordinator()
        return self._transition_coordinator_instance

    @property
    def _shared_deps(self) -> SharedHandlerDeps:
        """What the mode handlers share, rebuilt with the option caches.

        Its ``light_applier`` is the one applier of the instance's own light
        changes, so the switch and the handlers record commands the same way.
        """
        if self._shared_deps_instance is None:
            self._shared_deps_instance = self._create_shared_deps()
        return self._shared_deps_instance

    def _create_shared_deps(self) -> SharedHandlerDeps:
        return SharedHandlerDeps(
            hass=self.hass,
            instance_name=self._instance_name,
            lights=self._lights,
            state_ctrl=self._state_ctrl,
            is_control_brightness_on=self._is_control_brightness_on,
            is_control_color_on=self._is_control_color_on,
            get_transition=self._get_transition,
            on_applied=self.record_applied_target,
            mark_applied=self._manual_control_detector.mark_applied,
            is_in_grace_period=self._manual_control_detector.is_in_grace_period,
            get_night_brightness=self._dials.dialled_in_night,
            get_day_brightness=self._dials.dialled_in_day,
            get_held_lights=self._state_ctrl.get_held_lights,
            is_safety_room_on=self._is_safety_room_on,
        )

    def _create_mode_handlers(self) -> ModeHandlers:
        """Create mode handlers with current configuration."""
        cfg = self._config
        shared = self._shared_deps
        return ModeHandlers(
            day=DayModeHandler(
                shared=shared,
                config=cfg.day_mode,
                illuminance=self._illuminance,
                weather=self._weather,
                circadian=self._circadian,
            ),
            night=NightModeHandler(
                shared=shared,
                config=cfg.night_mode,
                motion=self._motion,
                action_scheduler=self._action_scheduler,
                circadian=self._circadian,
            ),
            sleep=SleepModeHandler(
                shared=shared,
                config=cfg.sleep_mode,
                illuminance=self._illuminance,
                day_mode_config=cfg.day_mode,
                night_mode_config=cfg.night_mode,
                schedule=self._schedule,
                circadian=self._circadian,
            ),
            wakeup=WakeUpModeHandler(
                shared=shared,
                config=cfg.wake_up_mode,
                illuminance=self._illuminance,
                schedule=self._schedule,
                circadian=self._circadian,
                day_mode_config=cfg.day_mode,
                night_mode_config=cfg.night_mode,
            ),
        )

    def _create_transition_coordinator(self) -> TransitionCoordinator:
        """Create transition coordinator with current handlers."""
        return TransitionCoordinator(
            hass=self.hass,
            instance_name=self._instance_name,
            handlers=self._handlers.by_mode(),
            lights=self._lights,
            motion=self._motion,
            state_ctrl=self._state_ctrl,
            get_transition=self._get_transition,
            is_control_brightness_on=self._is_control_brightness_on,
            is_control_color_on=self._is_control_color_on,
            on_applied=self.record_applied_target,
            mark_applied=self._manual_control_detector.mark_applied,
        )

    # ---------------------------------------------------------------
    #  Mode / switch helpers
    # ---------------------------------------------------------------

    def _invalidate_option_caches(self) -> None:
        """Drop everything built from the options, so it is rebuilt from new ones.

        The state controller and the action scheduler survive: one holds the
        persisted state, the other the pending timers of the instance.
        """
        self._illuminance_reader = None
        self._motion_instance = None
        self._lights_instance = None
        self._circadian_instance = None
        self._manual_control_detector_instance = None
        self._expectation_adopter_instance = None
        self._external_control_instance = None
        self._weather_instance = None
        self._shared_deps_instance = None
        self._mode_handlers_instance = None
        self._transition_coordinator_instance = None
        self._discovery.invalidate()
        self._discovery.forget_adopted()
        _LOGGER.debug(
            "[%s] Invalidated option caches, schedule, and mode handlers",
            self._instance_name,
        )

    def _is_day_mode(self) -> bool:
        return self._schedule.is_day_mode()

    def _entity(self, key: str) -> Any | None:
        """Another entity of this instance, None before it is set up."""
        return instance_entity(self.hass, self._config_entry.entry_id, key)

    def _is_control_brightness_on(self) -> bool:
        return is_entity_on(self._entity(KEY_CONTROL_BRIGHTNESS), default=True)

    def _is_control_color_on(self) -> bool:
        return is_entity_on(self._entity(KEY_CONTROL_COLOR), default=True)

    def has_lux_sensor(self) -> bool:
        """True if this instance regulates against a LUX measurement.

        The options alone cannot answer this: with area discovery the sensors
        are found in the area and never written to the config entry.
        """
        return self._illuminance.get_light_sensor_entity() is not None

    def has_motion_sensor(self) -> bool:
        """True if this instance drives night mode against a motion sensor.

        The options alone cannot answer this: with area discovery the sensors
        are found in the area and never written to the config entry.
        """
        return self._motion.get_motion_sensor_entity() is not None

    def _is_motion_lit(self, mode: str) -> bool:
        """True when *mode* is a night that motion, not the clock, drives.

        The one definition of "motion-lit night": the tick, the release and
        the safety lock all ask it, so they cannot disagree about when the
        lights follow the motion sensor.
        """
        return mode == MODE_NIGHT and self.has_motion_sensor()

    def is_wall_buttons_blocked(self) -> bool:
        """True when the wall-button services must be ignored (safety lock).

        Only meaningful at night in a motion-lit room: the "Block wall
        buttons" switch is on and a motion sensor is configured, so motion
        alone decides. Used by the services and :meth:`adjust_brightness`.
        """
        block = self._entity(KEY_BLOCK_WALL_BUTTONS)
        if not is_entity_on(block, default=False):
            return False
        return self._is_motion_lit(self._schedule.get_current_mode())

    def _is_safety_room_on(self) -> bool:
        """True while the safety room (force defaults) is armed.

        The safety room is the same switch that blocks wall buttons: in a
        motion-lit room at night it both ignores visitor input *and* enforces
        the configured defaults on every light, even the ones a service holds.
        """
        return self.is_wall_buttons_blocked()

    def _get_transition(self, context: str = "tick") -> int:
        if context == "initial":
            return int(
                self._options.get(
                    CONF_INITIAL_TRANSITION_SECONDS,
                    DEFAULT_INITIAL_TRANSITION_SECONDS,
                )
            )
        if context == "mode":
            return int(
                self._options.get(
                    CONF_MODE_TRANSITION_SECONDS,
                    DEFAULT_MODE_TRANSITION_SECONDS,
                )
            )
        value = int(
            self._options.get(CONF_TRANSITION_SECONDS, DEFAULT_TRANSITION_SECONDS)
        )
        return min(value, MAX_TICK_TRANSITION_SECONDS)

    # ---------------------------------------------------------------
    #  Hold validation / release
    # ---------------------------------------------------------------

    def _in_ramp(self) -> bool:
        """True while a sleep or wake-up ramp is moving the values itself."""
        return self._handlers.sleep.is_sleep_active() or self._handlers.wakeup.is_active()

    def _detection_policy(self) -> DetectionPolicy:
        """The tolerances and axes a light is judged with right now.

        Single source of truth for the ruler: the event-driven detection and
        the re-validation of a restored hold both use it. Inside a sleep or
        wake-up ramp only on/off is judged, because the ramp legitimately
        moves brightness and colour.
        """
        brightness_tol, kelvin_tol = ManualControlDetector.get_tolerances_for_mode(
            self._schedule.get_current_mode(),
            self._illuminance.get_light_sensor_entity() is not None,
        )
        in_ramp = self._in_ramp()
        return DetectionPolicy(
            brightness_tolerance_pct=brightness_tol,
            kelvin_tolerance=kelvin_tol,
            check_brightness=not in_ramp and self._is_control_brightness_on(),
            check_color=not in_ramp and self._is_control_color_on(),
        )

    def _forget_applied_values(self) -> None:
        """Let every mode handler drop its memory of its own commands."""
        for handler in self._handlers:
            handler.forget_applied_values()

    # ---------------------------------------------------------------
    #  Central tick
    # ---------------------------------------------------------------

    def _handle_tick(self) -> None:
        """Central tick: detect mode, transitions, dispatch to mode handler."""
        try:
            self._tick_once()
        finally:
            # The guard exists so the state reports caused by the handlers'
            # first apply are not read as external control. Every path here
            # has had that chance, including the motion-lit night, which
            # returns early by design — leaving the guard set would silently
            # disable detection for the whole night.
            self._first_tick_after_startup = False

    def _tick_once(self) -> None:
        """One tick, without the startup guard."""
        self._release_expired_holds()
        if self._first_tick_after_startup and self._restored_holds.has_pending:
            # The lamps report asynchronously. A report that arrived between
            # the load-time check and the subscription would otherwise leave
            # its hold unvalidated forever; judge it now, against the snapshot.
            self._restored_holds.revalidate_pending()
        if self._run_service_mode():
            return

        # Normal mode evaluation
        mode = self._schedule.get_current_mode()

        # Log context
        sun = self.hass.states.get("sun.sun")
        night_mode_type, night_start_str = self._schedule.get_mode_and_time_for_log()
        _LOGGER.debug(
            "[%s] Tick: mode=%s (night_mode=%s, night_start=%s, sun=%s, time=%s)",
            self._instance_name,
            mode,
            night_mode_type,
            night_start_str,
            sun.state if sun else "?",
            dt_util.now().strftime("%H:%M"),
        )

        # Detect mode transitions. The transition reports the new mode, which
        # records it; the assignment below also covers the first tick and a
        # transition that raised.
        if self._last_mode is not None and self._last_mode != mode:
            try:
                self._handle_mode_transition(self._last_mode, mode)
            except Exception:
                _LOGGER.exception(
                    "[%s] Error during mode transition %s→%s",
                    self._instance_name,
                    self._last_mode,
                    mode,
                )
        self._last_mode = mode

        # External control detection is event-driven (see ExternalControlMonitor),
        # so the tick only has to apply the mode.
        self._apply_mode_now(mode)

    def _run_service_mode(self) -> bool:
        """Serve the service-started states that outrank the schedule.

        Returns True when one of them owns the lights right now, so the
        schedule's mode must not be applied: the sleep dimming, the dark
        block after it, and a wake-up started by service.
        """
        sleep_handler = self._handlers.sleep

        # Priority 1: Check if sleep is currently active (dimming phase)
        if sleep_handler.is_sleep_active():
            _LOGGER.debug(
                "[%s] Tick: Sleep Mode active (dimming phase)",
                self._instance_name,
            )
            sleep_handler.tick()
            return True

        # Priority 2: Check if sleep block is active (post-sleep OFF state)
        if sleep_handler.is_block_active():
            mode = self._schedule.get_current_mode()
            if mode == MODE_DAY:
                _LOGGER.info(
                    "[%s] Sleep Mode: Block cleared (day mode started)",
                    self._instance_name,
                )
                sleep_handler.clear_block()
            elif mode == MODE_NIGHT:
                if self._is_motion_lit(mode) and self._motion.has_motion_now():
                    _LOGGER.info(
                        "[%s] Sleep Mode: Block cleared (motion detected)",
                        self._instance_name,
                    )
                    sleep_handler.clear_block()
                else:
                    _LOGGER.debug(
                        "[%s] Tick: Sleep Mode block active - no light control",
                        self._instance_name,
                    )
                    return True
            else:
                _LOGGER.debug(
                    "[%s] Tick: Sleep Mode block active - no light control",
                    self._instance_name,
                )
                return True

        # Priority 3: Check if wake-up is service-triggered and active
        wakeup_handler = self._handlers.wakeup
        if wakeup_handler.is_service_triggered_active():
            _LOGGER.debug(
                "[%s] Tick: Wake-up Mode service-triggered active",
                self._instance_name,
            )
            wakeup_handler.tick()
            return True

        return False

    def _apply_mode_now(self, mode: str) -> None:
        """Apply *mode* to the lights, respecting how that mode is driven.

        Night mode with a motion sensor is driven by motion rather than by
        the tick, so its lights are only touched while motion is present.
        """
        if self._is_motion_lit(mode):
            if self._motion.has_motion_now():
                self._handlers.night.handle_motion_on()
            return
        handler = self._get_mode_handler(mode)
        if handler is not None:
            handler.tick()

    def _handle_mode_transition(self, from_mode: str, to_mode: str) -> None:
        """Route mode transitions to transition coordinator (synchronous)."""
        transition_key = f"{from_mode}→{to_mode}"

        _LOGGER.debug(
            "[%s] Mode transition: %s",
            self._instance_name,
            transition_key,
        )

        self._report_mode_change(from_mode, to_mode)

        # Entering the night starts from the configured brightness again, so
        # that yesterday's dial does not carry into tonight. Reset before the
        # coordinator applies the new mode's values.
        self._dials.reset_for_mode(to_mode)

        self._clear_holds_entering(to_mode)
        self.notify_monitors()

        if self._transition_coordinator is not None:
            # Call transition synchronously to avoid race with tick()
            # This ensures enter()/exit() complete before tick() runs
            self._transition_coordinator.transition_sync(from_mode, to_mode)

    def _clear_holds_entering(self, mode: str) -> None:
        """End the holds that do not outlive the start of *mode*.

        A service hold (turn_on/turn_off with hold:true) only lives within its
        phase: entering the next phase lets the automation take over from a
        clean default again. A detected hold is different — it records a
        foreign intervention (a scene, a manual dim), so it survives the phase
        change unless the instance opts out. Both reasons can expire.

        Sleep and wake-up are the exception: they are asked for, by the clock
        or by an alarm, and a hold left over from the evening would keep them
        from reaching the very lights they exist for. They end every hold.
        """
        self._state_ctrl.clear_holds(
            keep_detected=(
                self._config.detected_hold_survives_phase
                and mode not in (MODE_SLEEP, MODE_WAKEUP)
            )
        )

    # ---------------------------------------------------------------
    #  Motion handling
    # ---------------------------------------------------------------

    def _handle_motion_on(self) -> None:
        """Night mode: motion/presence detected → turn on lights."""
        night_handler = self._handlers.night
        if self._last_mode == MODE_DAY:
            # The clock already says night, but the tick has not run the
            # day→night transition yet.
            night_handler.expect_previous_mode_values()
        night_handler.handle_motion_on()

    def _handle_motion_off(self) -> None:
        """Night mode: motion/presence cleared → schedule off timer."""
        self._handlers.night.handle_motion_off()

    # ---------------------------------------------------------------
    #  Listeners
    # ---------------------------------------------------------------

    def _start_listeners(self) -> None:
        """Subscribe to sensor changes and per-minute tick, then apply once."""
        self._stop_listeners()
        self._invalidate_option_caches()

        lux_cal = self._state_ctrl.get_lux_calibration()
        if lux_cal is not None:
            self._illuminance.set_lux_calibration(lux_cal)

        self._subscribe()

        # Record the adopted entity set now, so registry events only trigger a
        # re-discover when that set actually changes.
        self._discovery.remember_adopted()

        self._apply_initial_mode()

    def _subscribe(self) -> None:
        """Listen to the sensors, the lights, the clock and the registries."""
        hass = self.hass

        light_sensors = self._illuminance.get_light_sensor_entities()
        if light_sensors:
            self._unsub.append(
                async_track_state_change_event(hass, light_sensors, self._on_tick)
            )
            _LOGGER.debug(
                "[%s] Subscribed to %d illuminance sensors: %s",
                self._instance_name,
                len(light_sensors),
                light_sensors,
            )

        self._unsub.append(async_track_time_change(hass, self._on_tick, second=0))

        motion_sensors = self._motion.get_motion_sensor_entities()
        if motion_sensors:
            self._unsub.append(
                async_track_state_change_event(hass, motion_sensors, self._on_motion)
            )
            _LOGGER.debug(
                "[%s] Subscribed to %d motion sensors: %s",
                self._instance_name,
                len(motion_sensors),
                motion_sensors,
            )

        # Light state changes drive the event-driven external control detection.
        lights = self._lights.get_lights_list()
        if lights:
            self._unsub.append(
                async_track_state_change_event(
                    hass, lights, self._on_light_state_change
                )
            )
            _LOGGER.debug(
                "[%s] Subscribed to state changes for %d lights (event-driven detection)",
                self._instance_name,
                len(lights),
            )

        # Re-discover the area the moment its registries change, so a newly
        # added lamp or sensor is adopted within seconds — no per-minute poll.
        for event in (
            EVENT_ENTITY_REGISTRY_UPDATED,
            EVENT_DEVICE_REGISTRY_UPDATED,
            EVENT_AREA_REGISTRY_UPDATED,
        ):
            self._unsub.append(hass.bus.async_listen(event, self._on_registry_changed))

    def _apply_initial_mode(self) -> None:
        """Apply the current mode once, right after (re)subscribing."""
        mode = self._schedule.get_current_mode()
        self._last_mode = mode
        self._report_mode_change(None, mode)
        # Skip external control detection until the mode handlers have applied
        # their initial values.
        self._first_tick_after_startup = True
        if mode == MODE_WAKEUP:
            self._handlers.wakeup.tick()
        else:
            # Day and sleep apply their values, night applies its fallback or
            # handles motion.
            self._on_tick()

    @callback
    def _on_tick(self, _: Any = None) -> None:
        """The minute tick, or a LUX reading: apply the current mode."""
        if not self._attr_is_on:
            return
        try:
            self._handle_tick()
        except Exception:
            _LOGGER.exception("[%s] Error in _handle_tick", self._instance_name)
        # The LUX mirror sensor reads the raw sensor state, so it must
        # refresh whenever the underlying reading (or the minute tick) runs.
        self.notify_monitors()

    @callback
    def _on_motion(self, ev: Any) -> None:
        """A motion sensor changed; only the night follows motion."""
        if not self._attr_is_on:
            return
        if self._is_day_mode():
            return
        to_state = ev.data.get("new_state")
        if to_state is None:
            return
        try:
            if to_state.state == STATE_ON:
                self._handle_motion_on()
            else:
                self._handle_motion_off()
        except Exception:
            _LOGGER.exception("[%s] Error in motion handler", self._instance_name)
        # Refresh the "motion now" mirror sensor.
        self.notify_monitors()

    @callback
    def _on_light_state_change(self, ev: Any) -> None:
        """A configured light reported a state: judge it for external control."""
        if not self._attr_is_on:
            return

        entity_id = ev.data.get("entity_id")
        if entity_id not in self._lights.get_lights_list():
            return

        try:
            self._external_control.handle_state_report(entity_id)
        except Exception:
            _LOGGER.exception(
                "[%s] Error in light state change handler", self._instance_name
            )

    def _stop_listeners(self) -> None:
        """Unsubscribe all and reset transient state."""
        for unsub in self._unsub:
            unsub()
        self._unsub.clear()
        if self._registry_debounce is not None:
            self._registry_debounce.cancel()
            self._registry_debounce = None
        self._last_mode = None
        self._last_applied_target = None
        self.notify_monitors()

        self._handlers.night.exit("")

        if self._illuminance_reader is not None:
            self._illuminance_reader.clear_state()

    # ---------------------------------------------------------------
    #  Monitoring API (read by sensor.py, fed by the light applier)
    # ---------------------------------------------------------------

    def get_active_mode(self) -> str | None:
        """Return the mode driving this instance, None while it is off.

        A sleep or wake-up started by service drives the lights although the
        schedule never entered that mode, so it is what the room is in.
        ``_last_mode`` stays untouched: it is the schedule's side of the
        transition machinery, and the ramp must not trigger transitions of
        its own.
        """
        if self._last_mode is None:
            return None
        return self._service_ramp_mode() or self._last_mode

    def _service_ramp_mode(self) -> str | None:
        """The service-started ramp moving the lights right now, if any.

        Same order as :meth:`_run_service_mode`, which decides who owns the
        lights; the dark block after a sleep is not a ramp and is not listed.
        """
        if self._handlers.sleep.is_sleep_active():
            return MODE_SLEEP
        if self._handlers.wakeup.is_service_triggered_active():
            return MODE_WAKEUP
        return None

    def get_held_lights(self) -> set[str]:
        """Lights currently held by a service until the phase ends."""
        return self._state_ctrl.get_held_lights()

    def get_held_lights_with_reasons(self) -> dict[str, str]:
        """Currently held lights mapped to *why* they are held."""
        return self._state_ctrl.get_held_lights_with_reasons()

    def get_last_applied_target(self) -> ExpectedState | None:
        """Return the values we last commanded, None if nothing was sent yet.

        This is what the integration asked for, not what the lights report.
        Comparing the two is the point of the monitoring.
        """
        return self._last_applied_target

    def get_mode_progress(self) -> float | None:
        """Return ramp progress in sleep and wake-up, None in other modes."""
        mode = self.get_active_mode()
        if mode not in (MODE_SLEEP, MODE_WAKEUP):
            return None
        ramp = self._handlers.sleep if mode == MODE_SLEEP else self._handlers.wakeup
        return ramp.get_progress()

    def get_controlled_lights(self) -> list[str]:
        """Lights this instance currently manages (configured or discovered)."""
        return self._lights.get_lights_list()

    def get_discovery_info(self) -> dict[str, Any]:
        """Area-discovery picture, or an empty dict for a non-area instance.

        Mirrors the ``extra_state_attributes`` of the main switch, but as a
        stable read-only accessor for the discovery sensors.
        """
        cfg = self._config
        if not (cfg.is_area_based() and cfg.area_id):
            return {}
        discovery = self._discovery.scan()
        return {
            "area_name": discovery.get("area_name"),
            "area_id": cfg.area_id,
            "lights_in_area": discovery.get("lights_in_area", []),
            "motion_sensors": discovery.get("motion_sensors", []),
            "illuminance_sensors": discovery.get("illuminance_sensors", []),
            "included_lights": list(cfg.included_lights),
            "controlled_lights": self._lights.get_lights_list(),
        }

    def get_motion_sensor_entities(self) -> list[str]:
        """Motion/presence sensors in effect (configured or discovered)."""
        return self._motion.get_motion_sensor_entities()

    def get_active_motion_sensors(self) -> list[str]:
        """Motion/presence sensors that are currently on."""
        return self._motion.get_active_motion_sensors()

    def get_motion_now(self) -> bool:
        """True while motion is present, as the integration sees it."""
        return self.has_motion_sensor() and self._motion.has_motion_now()

    def read_raw_lux(self) -> float | None:
        """The raw LUX reading of the light sensor, None when it has none."""
        return self._illuminance.get_lux_raw()

    def store_lux_calibration(self, lamp_contribution_lux: float) -> None:
        """Persist the lamp contribution at 100% and apply it to the reader.

        Persisted so it survives a restart, and set on the live reader so it
        applies without one.
        """
        self._state_ctrl.set_lux_calibration(lamp_contribution_lux)
        self._illuminance.set_lux_calibration(lamp_contribution_lux)

    def get_lux_reading(self) -> dict[str, Any]:
        """Raw LUX plus the compensated ambient value, without side effects.

        Unlike ``get_lux()``, which returns a rolling measurement average,
        this reports the current raw reading and its compensated value.
        It does not sample a new measurement into the smoothing buffer.
        Compensation uses the calibration and last applied brightness.
        """
        raw = self._illuminance.get_lux_raw()
        calibration = self._illuminance.get_lux_calibration()
        brightness = self._illuminance.get_last_applied_brightness()
        compensated = (
            calculate_compensated_lux(raw, calibration, brightness)
            if raw is not None
            else None
        )
        return {
            "raw": raw,
            "compensated": compensated,
            "calibrated": calibration is not None,
            "lamp_contrib_lux": calibration,
            "last_applied_brightness_pct": brightness,
            "sensors": self._illuminance.get_light_sensor_entities(),
        }

    def _report_mode_change(self, from_mode: str | None, to_mode: str) -> None:
        """Record the new mode and publish it for sensors and automations.

        The mode is set *here* rather than at the call site because the
        sensors re-read `get_active_mode()` while this runs. Setting it
        afterwards left them reporting the mode we had just left, and in a
        night-with-motion room nothing else would notify them until the next
        time a light was actually switched.
        """
        self._last_mode = to_mode
        self.hass.bus.async_fire(
            EVENT_MODE_CHANGED,
            {
                "entry_id": self._config_entry.entry_id,
                "instance": self._instance_name,
                "area_id": self._config.area_id,
                "from_mode": from_mode,
                "to_mode": to_mode,
            },
        )
        self.notify_monitors()

    def record_applied_target(self, applied: ExpectedState) -> None:
        """Observe what the light applier just commanded.

        Handed to the light applier as its callback, so the monitor sensors
        can show the last target without reaching into the handlers.
        """
        self._last_applied_target = applied
        self.notify_monitors()

    def notify_monitors(self) -> None:
        """Tell this instance's sensors to re-read."""
        async_dispatcher_send(
            self.hass,
            SIGNAL_MONITOR_UPDATE.format(entry_id=self._config_entry.entry_id),
        )

    # ---------------------------------------------------------------
    #  Public API (used by services.py and number.py)
    # ---------------------------------------------------------------

    def adjust_brightness(self, step: int) -> str:
        """Dim or brighten by *step*, in whatever way this instance can hold it.

        A step is applied to the lights where nothing here controls their
        brightness, it moves the target where we aim at a fixed value, and it
        is ignored where neither is possible. Manual control is never
        involved: a press is our own doing, not an intervention to step
        aside for.

        A dim press is a visitor action like turn_on/turn_off, so it
        supersedes an earlier hold: after turning the lights off, dimming
        still reaches them.

        Returns a short reason for the service to log.
        """
        if self.is_wall_buttons_blocked():
            return "wall buttons blocked, ignored"

        mode = self._schedule.get_current_mode()

        if mode == MODE_NIGHT:
            dial = self._dials.night()
            if dial is None:
                return "no night brightness dial, ignored"
            self._state_ctrl.clear_holds()
            self.notify_monitors()
            dial.set_dialled_in(dial.native_value + step)
            return f"night brightness now {dial.native_value}%"

        if mode != MODE_DAY:
            return f"ignored, mode={mode} runs a ramp of its own"

        # Day mode only has a single target on the *fixed* fallback without a
        # LUX sensor. With a LUX sensor the curve keeps regulating, so a step
        # cannot be held; the other fallbacks set no brightness at all.
        if self.has_lux_sensor():
            return "ignored, day mode is LUX-regulated"

        fallback = self._config.day_mode.fallback
        if fallback == DAY_FALLBACK_FIXED:
            self._state_ctrl.clear_holds()
            self.notify_monitors()
            return self._step_day_brightness(step)

        if fallback == DAY_FALLBACK_SKIP:
            # Day mode leaves the brightness alone here, so the step stands.
            self._state_ctrl.clear_holds()
            self.notify_monitors()
            self._shared_deps.light_applier.step_brightness(
                self._lights.get_lights_list(), step, floor=MIN_DIAL_BRIGHTNESS_PCT
            )
            return f"day fallback={fallback} sets no brightness, stepped the lights"

        if fallback == DAY_FALLBACK_CIRCADIAN_ONLY:
            return "ignored, day fallback=circadian_only controls colour only"

        return f"ignored, day fallback={fallback} wants the lights off"

    def _step_day_brightness(self, step: int) -> str:
        """Move the day brightness dial (fixed fallback) by *step*.

        The dial holds an absolute brightness, like the night dial, so a step
        simply shifts the target; the day handler reads the dialled-in value
        and re-applies it.
        """
        dial = self._dials.day()
        if dial is None:
            return "no day brightness dial, ignored"
        dial.set_dialled_in(dial.native_value + step)
        return f"day brightness now {dial.native_value}%"

    def reapply_current_mode(self) -> None:
        """Apply the current mode now, without waiting for the next tick.

        Used when something changed the target in between: the end of a
        manual episode, the scene blocker going off and the brightness dials.
        A service-started sleep or wake-up outranks the schedule here exactly
        as it does on the tick.
        """
        if not self._run_service_mode():
            self._apply_mode_now(self._schedule.get_current_mode())

    def reapply_dialled_brightness(self) -> None:
        """Re-apply the brightness after a brightness dial changed.

        Night mode re-dims the lights that are already on: a dial is not an
        on switch, and motion alone decides when the room is lit. Every other
        mode re-applies exactly what the next tick would.
        """
        if self._schedule.get_current_mode() == MODE_NIGHT:
            self._handlers.night.reapply_brightness_to_on_lights()
            return
        self.reapply_current_mode()

    def get_desired_turn_on_params(self, *, force_on: bool = False) -> dict[str, Any]:
        """Return our desired brightness/colour for light.turn_on.

        *force_on* is set for an explicit wall-button ``turn_on``
        (``hold: true``): a brightness the mode would leave at 0 (off) is
        lifted to a positive value so the light actually switches on, even
        when the LUX curve considers the room bright enough
        (``day_min_brightness`` 0 and LUX at/above ``lux_off``).
        """
        result: dict[str, Any] = {}

        if self._is_control_brightness_on():
            if self._is_day_mode():
                pct = self._handlers.day.get_brightness_pct()
                if pct is None and force_on:
                    pct = self._handlers.day.max_brightness()
                result["brightness_pct"] = pct if pct is not None else 0
            else:
                result["brightness_pct"] = self._handlers.night.get_brightness_pct()

        if self._is_control_color_on() and self._circadian.is_enabled():
            kelvin = self._circadian.get_expected_night_kelvin()
            if kelvin is not None:
                result["color_temp_kelvin"] = kelvin

        return result

    def record_lights_turned_on_by_service(
        self,
        lights: list[str],
        hold: bool = True,
    ) -> None:
        """Record lights turned on via daynight_lighting.turn_on.

        With *hold* the lights are held on until the phase ends, protected
        from the night motion-off timer. Without it the lights are only
        switched: the day/night automation keeps managing them, so a system
        automation does not fight the loop.
        """
        self._state_ctrl.mark_controlled(lights)
        if hold:
            # The visitor wants them on until the phase ends, whatever the
            # day/night automation would do. A held light is not even in the
            # off timer's list, so it is protected without ``keep_on``.
            self._state_ctrl.set_hold(lights, reason=HOLD_REASON_SERVICE)
            self._handlers.night.cancel_off_timer()
        self.notify_monitors()

    def prepare_lights_applied_by_service(
        self,
        lights: list[str],
        *,
        on: bool,
        brightness_pct: int | None = None,
        kelvin: int | None = None,
    ) -> None:
        """Record expected state before a service switches the lights.

        Services call the light domain blocking, so the state change event
        fires before they return. Expected state must already match what we
        are about to set — otherwise event-driven detection reports our own
        change as external control.
        """
        self._manual_control_detector.mark_applied(lights)
        for lid in lights:
            self._state_ctrl.set_expected_state(
                lid, on=on, brightness_pct=brightness_pct, kelvin=kelvin
            )

    def prepare_lights_turn_off_by_service(self, lights: list[str]) -> None:
        """Prepare for a daynight_lighting.turn_off before the lights switch."""
        self.prepare_lights_applied_by_service(lights, on=False)

    def record_lights_turned_off_by_service(
        self, lights: list[str], hold: bool = True
    ) -> None:
        """Record lights turned off via daynight_lighting.turn_off.

        With *hold* the lights are held off until the phase ends, so the
        day/night automation does not switch them straight back on. Without
        it they are only switched off: the automation keeps managing them.
        """
        self._state_ctrl.unmark_controlled(lights)
        if hold:
            # The visitor wants them off until the phase ends, whatever the
            # day/night automation would do.
            self._state_ctrl.set_hold(lights, reason=HOLD_REASON_SERVICE)
            self._interrupt_ramps()
        self.notify_monitors()

    def _interrupt_ramps(self) -> None:
        """End a running sleep/wake-up ramp when a visitor turns the room off.

        A ``turn_off`` with ``hold: true`` is the same input as a foreign
        app's OFF: the whole ramp stops and the room jumps into the dark
        block. Without the hold (a system automation) the ramp keeps running.
        """
        if self._handlers.sleep.is_sleep_active():
            self._handlers.sleep.interrupt_into_block()

        if self._handlers.wakeup.is_active():
            self._handlers.wakeup.interrupt_into_block()

    def hold_all_lights(self) -> None:
        """Hold every light of the instance until the phase ends.

        The bulk replacement for the removed "Manual control" switch: a single
        call that stops the automation from touching any light.
        """
        lights = self._lights.get_lights_list()
        if lights:
            self._state_ctrl.set_hold(lights, reason=HOLD_REASON_SERVICE)
        self.notify_monitors()

    def release_hold(self) -> None:
        """Drop the holds and put the lights into the state a release promises.

        A hold is a visitor's deviation from the configured behavior, so
        ending it returns to that behavior: the brightness dials fall back to
        their configured starting points (exactly as entering the phase does)
        and the mode is applied again from those defaults.

        "Applied again" must hold in every situation, including the common one
        where the room is dark and nobody moves. So the release always takes
        exactly one branch of :meth:`_reapply_after_release` and reports it,
        and every light it freed without commanding stays with a truthful
        expectation (see :class:`ExpectationAdopter`).
        """
        # Collected before clearing: once the holds are gone the set is lost,
        # and both reasons — a visitor's command and a detected intervention —
        # must leave a defined state behind.
        released = sorted(self._state_ctrl.get_held_lights_with_reasons())
        self._resolve_holds(released, reset_dials=True)

    def _release_expired_holds(self) -> None:
        """Resolve elapsed holds through the same path as an explicit release."""
        expired = self._state_ctrl.expired_holds(self._config.hold_timeout_min)
        if expired:
            self._resolve_holds(expired, reset_dials=False)

    def _resolve_holds(self, released: list[str], *, reset_dials: bool) -> None:
        """Release selected lights, reapply the phase and adopt expectations."""
        self._state_ctrl.release_hold(released)
        if reset_dials:
            self._dials.reset_all(apply=False)
        # Somebody else owned the lights while held, so what we remember
        # having commanded is stale; without this the damping would compare
        # the new target against a fiction and skip.
        self._forget_applied_values()

        branch, commanded = self._reapply_after_release(released)
        adopted = self._expectation_adopter.adopt(released, commanded)

        _LOGGER.info(
            "[%s] hold released: %d light(s), branch=%s, commanded=%d, adopted=%d",
            self._instance_name,
            len(released),
            branch,
            len(commanded),
            len(adopted),
        )
        self.notify_monitors()

    def _reapply_after_release(self, released: list[str]) -> tuple[str, list[str]]:
        """Restore the phase after a release: one branch, and what it commanded.

        The release moment decides which branch applies — never whether
        anything happens at all:

        ``service-ramp``
            A service-started sleep or wake-up owns the values; its ramp keeps
            running and is not disturbed.
        ``night-motion`` / ``night-off`` / ``night-adopt``
            A motion-lit night: the night handler decides between re-applying
            the night target, switching off what the off timer would switch
            off, and commanding nothing (see ``NightModeHandler.handle_release``).
        ``mode-apply``
            Day, or night without a motion sensor: whatever the next tick
            would apply.

        A light counts as commanded when the applier recorded a new expected
        state for it: that write is what detection compares against, so it is
        the honest answer to "did we still command this light?".
        """
        stamps = {lid: self._state_ctrl.get_expected_timestamp(lid) for lid in released}

        if self._run_service_mode():
            branch = "service-ramp"
        elif self._is_motion_lit(self._schedule.get_current_mode()):
            branch = self._handlers.night.handle_release(released)
        else:
            self._apply_mode_now(self._schedule.get_current_mode())
            branch = "mode-apply"

        commanded = [
            lid
            for lid in released
            if self._state_ctrl.get_expected_timestamp(lid) != stamps[lid]
        ]
        return branch, commanded

    def has_dialled_brightness(self) -> bool:
        """True when the current mode's brightness dial is dialled in.

        A dim press moves the night dial at night, or the day dial on the
        fixed day fallback, without creating a hold. The release-hold button
        therefore has nothing to reset; this button is the dial's counterpart.
        """
        mode = self._schedule.get_current_mode()
        if mode == MODE_NIGHT:
            return self._dials.dialled_in_night() is not None
        if mode == MODE_DAY:
            return self._dials.dialled_in_day() is not None
        return False

    def reset_brightness(self) -> None:
        """Drop the current mode's dialled-in brightness, back to configured.

        Only the current phase's dial is touched — a dim press never reaches
        the other phase's dial, and leaving it alone avoids clearing a value
        that still belongs to another part of the day. The lights are then
        re-applied at the configured brightness, exactly like a dial change:
        in a motion-lit night that re-dims the lights already on, rather than
        running the motion handler and re-holding them as a "divergence".
        """
        self._dials.reset_for_mode(self._schedule.get_current_mode(), apply=False)
        self.reapply_dialled_brightness()
        self.notify_monitors()

    def start_sleep_mode_now(
        self,
        duration_min: int | None = None,
        brightness_pct: int | None = None,
        color_temp_kelvin: int | None = None,
    ) -> None:
        """Immediately start Sleep Mode (service-triggered).

        Args:
            duration_min: Optional override for sleep duration in minutes
            brightness_pct: Optional override for target brightness
            color_temp_kelvin: Optional override for target kelvin
        """
        self._clear_holds_entering(MODE_SLEEP)
        sleep_handler = self._handlers.sleep
        # If any runtime overrides provided, use start_with_overrides
        if duration_min is not None or brightness_pct is not None or color_temp_kelvin is not None:
            sleep_handler.start_with_overrides(
                duration_min=duration_min,
                brightness_pct=brightness_pct,
                color_temp_kelvin=color_temp_kelvin,
            )
        else:
            sleep_handler.enter(None)
            sleep_handler.tick()
        self.notify_monitors()

    def start_wakeup_mode_now(
        self,
        duration_min: int | None = None,
        start_brightness_pct: int | None = None,
        end_brightness_pct: int | None = None,
        color_temp_kelvin: int | None = None,
    ) -> None:
        """Immediately start Wake-up Mode (service-triggered).

        Args:
            duration_min: Optional override for wake-up duration in minutes
            start_brightness_pct: Optional override for start brightness
            end_brightness_pct: Optional override for end brightness
            color_temp_kelvin: Optional override for end kelvin
        """
        self._clear_holds_entering(MODE_WAKEUP)
        # Clear any active sleep block when starting wake-up
        sleep_handler = self._handlers.sleep
        if sleep_handler.is_block_active():
            _LOGGER.info(
                "[%s] Wake-up Mode: Clearing active sleep block",
                self._instance_name,
            )
            sleep_handler.clear_block()

        self._handlers.wakeup.start_service_triggered(
            duration_min=duration_min if duration_min is not None else int(
                self._options.get(CONF_WAKEUP_DURATION_MIN, DEFAULT_WAKEUP_DURATION_MIN)
            ),
            start_brightness_pct=start_brightness_pct,
            end_brightness_pct=end_brightness_pct,
            color_temp_kelvin=color_temp_kelvin,
        )
        self.notify_monitors()

    def stop_sleep_mode_now(self) -> None:
        """Immediately stop Sleep Mode and return to normal day/night mode."""
        # Exit sleep mode, returning to normal schedule
        self._handlers.sleep.exit("")
        _LOGGER.info(
            "[%s] Sleep Mode stopped via service",
            self._instance_name,
        )
        self.notify_monitors()

    def stop_wakeup_mode_now(self) -> None:
        """Immediately stop Wake-up Mode and return to normal day/night mode."""
        # Exit wake-up mode, returning to normal schedule
        self._handlers.wakeup.exit("")
        _LOGGER.info(
            "[%s] Wake-up Mode stopped via service",
            self._instance_name,
        )
        self.notify_monitors()

    # ---------------------------------------------------------------
    #  Switch lifecycle
    # ---------------------------------------------------------------

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the switch on and start day/night logic."""
        self._attr_is_on = True
        _LOGGER.debug("[%s] Switch ON, starting listeners", self._instance_name)
        await self._state_ctrl.async_load()
        self._state_ctrl.prune(self._lights.get_lights_list())
        # A hold restored from storage predates this start; drop it if the
        # light no longer shows the intervention it was recorded for.
        self._release_expired_holds()
        self._restored_holds.revalidate_restored()
        # Taking over: the lights' current state predates our control, so the
        # moment we start listening it must not be read as an external change.
        self._manual_control_detector.mark_applied(self._lights.get_lights_list())
        self._start_listeners()
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the switch off and stop applying logic."""
        self._attr_is_on = False
        _LOGGER.debug("[%s] Switch OFF, stopping listeners", self._instance_name)
        self._stop_listeners()
        self.async_write_ha_state()

    async def async_will_remove_from_hass(self) -> None:
        """Stop listeners and cancel timers when the entity is removed.

        Disabling the config entry removes the entities without turning the
        switch off, so the per-minute tick and the sensor/light listeners
        would otherwise keep commanding the lights of a "disabled" instance.
        """
        self._stop_listeners()
        await super().async_will_remove_from_hass()

    def async_options_changed(self) -> None:
        """Called when options are updated in the UI."""
        if not self._attr_is_on:
            return
        _LOGGER.debug(
            "[%s] Options changed, restarting listeners and applying new settings",
            self._instance_name,
        )

        # A new configured night brightness is a deliberate new baseline, so
        # it wins over an ad-hoc dial. No apply needed, this method re-applies
        # everything below anyway.
        self._dials.reset_all(apply=False)

        # Save current mode before invalidating caches
        # (schedule/mode may change after new options are loaded)
        previous_mode = self._last_mode

        self._start_listeners()

        # Check if mode changed due to new options (e.g., night_start time changed)
        # This prevents false external control detection when mode transition happens
        # during options reload - the lights still have old mode's values but new
        # mode expects different values
        # Note: _start_listeners() sets _last_mode to current mode, so we compare
        # previous_mode with _last_mode to detect the transition
        if previous_mode is not None and previous_mode != self._last_mode:
            _LOGGER.debug(
                "[%s] Mode changed from %s to %s after options reload",
                self._instance_name,
                previous_mode,
                self._last_mode,
            )
            self._handle_mode_transition(previous_mode, self._last_mode)

        # Apply new settings immediately so user sees changes right away
        self._handle_tick()

    async def async_added_to_hass(self) -> None:
        """Restore state and start listeners if was on."""
        await super().async_added_to_hass()
        if (last_state := await self.async_get_last_state()) is not None:
            self._attr_is_on = last_state.state == STATE_ON
        _LOGGER.debug(
            "[%s] Added to HA, restored state=%s%s",
            self._instance_name,
            "on" if self._attr_is_on else "off",
            " (turn switch ON to start)" if not self._attr_is_on else "",
        )
        if self._attr_is_on:
            await self._state_ctrl.async_load()
            self._state_ctrl.prune(self._lights.get_lights_list())
            # A hold restored from storage predates this start; drop it if the
            # light no longer shows the intervention it was recorded for.
            self._release_expired_holds()
            self._restored_holds.revalidate_restored()
            # At HA startup the just-restored lights report their state
            # asynchronously, and colour bulbs briefly show an RGB/HS/XY colour
            # before the persisted colour temperature lands (the first tick
            # runs *before* that and skips, so no command marks them applied).
            # That transient is not an intervention: treat the restored lights
            # as "just applied" so the detector's grace period covers the
            # restore window instead of holding every light.
            self._manual_control_detector.mark_applied(self._lights.get_lights_list())
            self._start_listeners()
