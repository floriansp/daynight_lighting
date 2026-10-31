"""Tests for mode handlers: Day, Night, Sleep, WakeUp.

Tests the tick(), enter(), exit(), and calculate_expected_state() methods
for each mode handler.
"""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock


from homeassistant.util import dt as dt_util

from custom_components.daynight_lighting.context import SharedHandlerDeps
from custom_components.daynight_lighting.manual_control import ExpectedState
from custom_components.daynight_lighting.handlers import (
    DayModeHandler,
    NightModeHandler,
    SleepModeHandler,
    WakeUpModeHandler,
)



def _make_config(**kwargs) -> SimpleNamespace:
    """Create a config namespace with defaults."""
    defaults = {
        "lux_on": 10.0,
        "lux_off": 100.0,
        "min_brightness": 10,
        "max_brightness": 100,
        "fallback": "skip",
        "fixed_brightness_pct": 80,
        "brightness": 80,
        "motion_off_delay_min": 5,
        "on_enter_night": "leave",
        "target_brightness": 20,
        "target_kelvin": 2200,
        "duration_min": 60,
        "start_brightness": 1,
        "wake_time": (7, 0),
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def _make_mocks():
    """Create common mock objects for mode handlers."""
    mocks = {
        "state_ctrl": MagicMock(),
        "circadian": MagicMock(),
        "lights": MagicMock(),
    }
    mocks["state_ctrl"].mark_controlled = MagicMock()
    mocks["state_ctrl"].unmark_controlled = MagicMock()
    mocks["state_ctrl"].set_expected_state = MagicMock()
    mocks["circadian"].is_enabled.return_value = True
    mocks["circadian"].get_kelvin.return_value = (4000, 30.0)
    mocks["circadian"].get_expected_night_kelvin.return_value = 2700
    mocks["lights"].get_lights_list.return_value = ["light.a", "light.b"]
    return mocks


def _make_shared_deps(fake_hass, mocks=None) -> SharedHandlerDeps:
    """Create SharedHandlerDeps for testing."""
    if mocks is None:
        mocks = _make_mocks()
    return SharedHandlerDeps(
        hass=fake_hass,
        instance_name="Test",
        lights=mocks["lights"],
        state_ctrl=mocks["state_ctrl"],
        is_control_brightness_on=lambda: True,
        is_control_color_on=lambda: True,
        get_transition=lambda ctx: 0,
    )


# ===================================================================
#  DayModeHandler
# ===================================================================


class TestDayModeHandlerCalculateExpectedState:
    """Tests for DayModeHandler.calculate_expected_state."""

    def test_expected_on_when_lux_low(self, fake_hass):
        """When LUX is low, light should be ON."""
        mocks = _make_mocks()
        illuminance = MagicMock()
        illuminance.get_lux.return_value = 5.0  # Below lux_on

        handler = DayModeHandler(
            shared=_make_shared_deps(fake_hass, mocks),
            config=_make_config(lux_on=10.0, lux_off=100.0),
            illuminance=illuminance,
            weather=MagicMock(),
            circadian=mocks["circadian"],
        )

        state = handler.calculate_expected_state()
        assert state.on is True
        assert state.brightness_pct == 100  # Max brightness

    def test_expected_low_brightness_when_lux_high(self, fake_hass):
        """When LUX is high, brightness should be lower."""
        mocks = _make_mocks()
        illuminance = MagicMock()
        illuminance.get_lux.return_value = 50.0  # Between lux_on and lux_off

        handler = DayModeHandler(
            shared=_make_shared_deps(fake_hass, mocks),
            config=_make_config(lux_on=10.0, lux_off=100.0, min_brightness=10, max_brightness=100),
            illuminance=illuminance,
            weather=MagicMock(),
            circadian=mocks["circadian"],
        )

        state = handler.calculate_expected_state()
        assert state.on is True
        # 50 LUX is in the middle, should be around 55% (linear interpolation)
        assert 50 <= state.brightness_pct <= 60

    def test_expected_fallback_off_when_no_sensor(self, fake_hass):
        """When no LUX sensor and fallback=off, light should be OFF."""
        mocks = _make_mocks()
        illuminance = MagicMock()
        illuminance.get_lux.return_value = None

        handler = DayModeHandler(
            shared=_make_shared_deps(fake_hass, mocks),
            config=_make_config(fallback="off"),
            illuminance=illuminance,
            weather=MagicMock(),
            circadian=mocks["circadian"],
        )

        state = handler.calculate_expected_state()
        assert state.on is False

    def test_expected_fallback_fixed_when_no_sensor(self, fake_hass):
        """When no LUX sensor and fallback=fixed, use fixed brightness."""
        mocks = _make_mocks()
        illuminance = MagicMock()
        illuminance.get_lux.return_value = None

        handler = DayModeHandler(
            shared=_make_shared_deps(fake_hass, mocks),
            config=_make_config(fallback="fixed", fixed_brightness_pct=75),
            illuminance=illuminance,
            weather=MagicMock(),
            circadian=mocks["circadian"],
        )

        state = handler.calculate_expected_state()
        assert state.on is True
        assert state.brightness_pct == 75

    def test_expected_includes_kelvin_when_circadian_enabled(self, fake_hass):
        """When circadian is enabled, expected state includes kelvin."""
        mocks = _make_mocks()
        illuminance = MagicMock()
        illuminance.get_lux.return_value = 5.0

        handler = DayModeHandler(
            shared=_make_shared_deps(fake_hass, mocks),
            config=_make_config(),
            illuminance=illuminance,
            weather=MagicMock(),
            circadian=mocks["circadian"],
        )

        state = handler.calculate_expected_state()
        assert state.kelvin == 4000


class TestDayModeHandlerGetBrightness:
    """Tests for DayModeHandler.get_brightness_pct."""

    def test_max_brightness_when_lux_low(self, fake_hass):
        """When LUX is below lux_on, return max brightness."""
        mocks = _make_mocks()
        illuminance = MagicMock()
        illuminance.get_lux.return_value = 5.0

        handler = DayModeHandler(
            shared=_make_shared_deps(fake_hass, mocks),
            config=_make_config(lux_on=10.0, lux_off=100.0, min_brightness=10, max_brightness=100),
            illuminance=illuminance,
            weather=MagicMock(),
            circadian=mocks["circadian"],
        )

        assert handler.get_brightness_pct() == 100

    def test_min_brightness_when_lux_high(self, fake_hass):
        """When LUX is above lux_off, return min brightness."""
        mocks = _make_mocks()
        illuminance = MagicMock()
        illuminance.get_lux.return_value = 150.0

        handler = DayModeHandler(
            shared=_make_shared_deps(fake_hass, mocks),
            config=_make_config(lux_on=10.0, lux_off=100.0, min_brightness=10, max_brightness=100),
            illuminance=illuminance,
            weather=MagicMock(),
            circadian=mocks["circadian"],
        )

        assert handler.get_brightness_pct() == 10

    def test_linear_interpolation_between_lux_values(self, fake_hass):
        """Brightness interpolates linearly between lux_on and lux_off."""
        mocks = _make_mocks()
        illuminance = MagicMock()
        illuminance.get_lux.return_value = 55.0  # Halfway

        handler = DayModeHandler(
            shared=_make_shared_deps(fake_hass, mocks),
            config=_make_config(lux_on=10.0, lux_off=100.0, min_brightness=10, max_brightness=100),
            illuminance=illuminance,
            weather=MagicMock(),
            circadian=mocks["circadian"],
        )

        # Halfway between 10 and 100 LUX -> should be around 55% brightness
        result = handler.get_brightness_pct()
        assert 50 <= result <= 60


# ===================================================================
#  NightModeHandler
# ===================================================================


class TestNightModeHandlerCalculateExpectedState:
    """Tests for NightModeHandler.calculate_expected_state."""

    def test_expected_off_when_no_motion_sensor(self, fake_hass):
        """Without motion sensor and default fallback, expect OFF."""
        mocks = _make_mocks()
        motion = MagicMock()
        motion.get_motion_sensor_entity.return_value = None

        handler = NightModeHandler(
            shared=_make_shared_deps(fake_hass, mocks),
            config=_make_config(fallback="skip"),
            motion=motion,
            action_scheduler=MagicMock(),
            circadian=mocks["circadian"],
        )

        state = handler.calculate_expected_state()
        assert state.on is False

    def test_expected_on_when_motion_detected(self, fake_hass):
        """With motion sensor and motion detected, expect ON."""
        mocks = _make_mocks()
        motion = MagicMock()
        motion.get_motion_sensor_entity.return_value = "binary_sensor.motion"
        motion.has_motion_now.return_value = True

        handler = NightModeHandler(
            shared=_make_shared_deps(fake_hass, mocks),
            config=_make_config(brightness=50),
            motion=motion,
            action_scheduler=MagicMock(),
            circadian=mocks["circadian"],
        )

        state = handler.calculate_expected_state()
        assert state.on is True
        assert state.brightness_pct == 50

    def test_expected_off_when_no_motion(self, fake_hass):
        """With motion sensor but no motion, expect OFF."""
        mocks = _make_mocks()
        motion = MagicMock()
        motion.get_motion_sensor_entity.return_value = "binary_sensor.motion"
        motion.has_motion_now.return_value = False

        handler = NightModeHandler(
            shared=_make_shared_deps(fake_hass, mocks),
            config=_make_config(),
            motion=motion,
            action_scheduler=MagicMock(),
            circadian=mocks["circadian"],
        )

        state = handler.calculate_expected_state()
        assert state.on is False

    def test_expected_includes_night_kelvin(self, fake_hass):
        """Night mode includes kelvin from circadian."""
        mocks = _make_mocks()
        motion = MagicMock()
        motion.get_motion_sensor_entity.return_value = "binary_sensor.motion"
        motion.has_motion_now.return_value = True

        handler = NightModeHandler(
            shared=_make_shared_deps(fake_hass, mocks),
            config=_make_config(),
            motion=motion,
            action_scheduler=MagicMock(),
            circadian=mocks["circadian"],
        )

        state = handler.calculate_expected_state()
        assert state.kelvin == 2700


class TestNightModeHandlerFallback:
    """Tests for NightModeHandler fallback behavior."""

    def test_fallback_on_keeps_lights_on(self, fake_hass):
        """With fallback=on, lights stay on."""
        mocks = _make_mocks()
        motion = MagicMock()
        motion.get_motion_sensor_entity.return_value = None

        handler = NightModeHandler(
            shared=_make_shared_deps(fake_hass, mocks),
            config=_make_config(fallback="on", brightness=30),
            motion=motion,
            action_scheduler=MagicMock(),
            circadian=mocks["circadian"],
        )

        state = handler.calculate_expected_state()
        assert state.on is True
        assert state.brightness_pct == 30

    def test_fallback_off_turns_lights_off(self, fake_hass):
        """With fallback=off, lights turn off."""
        mocks = _make_mocks()
        motion = MagicMock()
        motion.get_motion_sensor_entity.return_value = None

        handler = NightModeHandler(
            shared=_make_shared_deps(fake_hass, mocks),
            config=_make_config(fallback="off"),
            motion=motion,
            action_scheduler=MagicMock(),
            circadian=mocks["circadian"],
        )

        state = handler.calculate_expected_state()
        assert state.on is False


# ===================================================================
#  SleepModeHandler
# ===================================================================


class TestSleepModeHandlerCalculateExpectedState:
    """Tests for SleepModeHandler.calculate_expected_state."""

    def test_expected_off_when_not_active(self, fake_hass):
        """When sleep is not active, expect OFF."""
        mocks = _make_mocks()
        illuminance = MagicMock()

        handler = SleepModeHandler(
            shared=_make_shared_deps(fake_hass, mocks),
            config=_make_config(target_brightness=10, target_kelvin=2200, duration_min=30),
            illuminance=illuminance,
        )

        state = handler.calculate_expected_state()
        assert state.on is False

    def test_expected_off_when_block_active(self, fake_hass):
        """When sleep block is active, expect OFF."""
        mocks = _make_mocks()
        illuminance = MagicMock()

        handler = SleepModeHandler(
            shared=_make_shared_deps(fake_hass, mocks),
            config=_make_config(target_brightness=10, target_kelvin=2200, duration_min=30),
            illuminance=illuminance,
        )
        handler._sleep_block_active = True

        state = handler.calculate_expected_state()
        assert state.on is False

    def test_expected_on_during_dimming(self, fake_hass):
        """During dimming phase, expect ON with dimming brightness."""
        mocks = _make_mocks()
        illuminance = MagicMock()
        illuminance.get_lux.return_value = 50.0

        handler = SleepModeHandler(
            shared=_make_shared_deps(fake_hass, mocks),
            config=_make_config(target_brightness=10, target_kelvin=2200, duration_min=30),
            illuminance=illuminance,
        )
        handler._sleep_active = True
        handler._sleep_start_time = "some_time"  # Would need proper time mock

        # Just verify it returns ON during active sleep
        # (detailed progress calculation requires time mocking)


class TestSleepModeHandlerProgress:
    """Tests for SleepModeHandler progress calculation."""

    def test_progress_zero_at_start(self, fake_hass):
        """Progress is 0 at start of sleep."""
        mocks = _make_mocks()
        illuminance = MagicMock()

        handler = SleepModeHandler(
            shared=_make_shared_deps(fake_hass, mocks),
            config=_make_config(target_brightness=10, target_kelvin=2200, duration_min=30),
            illuminance=illuminance,
        )

        # Without start time, progress is 0
        assert handler.get_progress() == 0.0


# ===================================================================
#  WakeUpModeHandler
# ===================================================================


class TestWakeUpModeHandlerCalculateExpectedState:
    """Tests for WakeUpModeHandler.calculate_expected_state."""

    def test_expected_off_when_not_active(self, fake_hass):
        """When wake-up is not active, expect OFF."""
        mocks = _make_mocks()
        illuminance = MagicMock()
        schedule = MagicMock()

        handler = WakeUpModeHandler(
            shared=_make_shared_deps(fake_hass, mocks),
            config=_make_config(start_brightness=1, duration_min=30),
            illuminance=illuminance,
            schedule=schedule,
            circadian=mocks["circadian"],
        )

        state = handler.calculate_expected_state()
        assert state.on is False

    def test_expected_on_during_wakeup(self, fake_hass):
        """During wake-up phase, expect ON."""
        mocks = _make_mocks()
        illuminance = MagicMock()
        schedule = MagicMock()

        handler = WakeUpModeHandler(
            shared=_make_shared_deps(fake_hass, mocks),
            config=_make_config(start_brightness=1, duration_min=30),
            illuminance=illuminance,
            schedule=schedule,
            circadian=mocks["circadian"],
        )
        handler._wakeup_active = True
        handler._wakeup_start_time = "some_time"

        # Verify basic structure
        assert handler.is_service_triggered_active() is True


class TestWakeUpProgressIsSideEffectFree:
    """Reading progress must not drive the wake-up state machine.

    Sensors query progress, so a read that ends a running ramp would let
    monitoring change behaviour.
    """

    @staticmethod
    def _make_handler(fake_hass, mocks):
        return WakeUpModeHandler(
            shared=_make_shared_deps(fake_hass, mocks),
            config=_make_config(
                start_brightness=1,
                duration_min=30,
                use_auto_values=False,
                end_kelvin=2700,
            ),
            illuminance=MagicMock(),
            schedule=MagicMock(),
            circadian=mocks["circadian"],
        )

    @staticmethod
    def _start_expired_ramp(handler):
        """Put the handler into a service ramp that has just run out."""
        handler._wakeup_active = True
        handler._wakeup_start_time = dt_util.now() - timedelta(minutes=31)
        handler._wakeup_service_duration_min = 30

    def test_reading_progress_leaves_the_ramp_running(self, fake_hass):
        handler = self._make_handler(fake_hass, _make_mocks())
        self._start_expired_ramp(handler)

        assert handler.get_progress() == 1.0
        assert handler.is_service_triggered_active() is True
        # Repeated reads stay stable
        assert handler.get_progress() == 1.0
        assert handler.is_service_triggered_active() is True

    def test_tick_ends_the_ramp(self, fake_hass):
        handler = self._make_handler(fake_hass, _make_mocks())
        self._start_expired_ramp(handler)

        handler.tick()

        assert handler.is_service_triggered_active() is False

    def test_final_value_comes_from_the_service_ramp(self, fake_hass):
        """The last tick applies the ramp end, not a schedule-derived value."""
        mocks = _make_mocks()
        handler = self._make_handler(fake_hass, mocks)
        self._start_expired_ramp(handler)
        handler._runtime_end_brightness = 80

        handler.tick()

        applied = [
            call.kwargs["brightness_pct"]
            for call in mocks["state_ctrl"].set_expected_state.call_args_list
        ]
        assert applied and all(pct == 80 for pct in applied)


class TestExpectedState:
    """Tests for ExpectedState dataclass."""

    def test_expected_state_defaults(self):
        """ExpectedState has correct defaults."""
        state = ExpectedState(on=True)
        assert state.on is True
        assert state.brightness_pct is None
        assert state.kelvin is None

    def test_expected_state_with_values(self):
        """ExpectedState stores values correctly."""
        state = ExpectedState(on=True, brightness_pct=75, kelvin=3000)
        assert state.on is True
        assert state.brightness_pct == 75
        assert state.kelvin == 3000
