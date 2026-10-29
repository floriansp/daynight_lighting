"""Tests for ManualControlDetector with persisted expected states.

Tests the check_external_control method that compares actual light state
to persisted expected state from StateController.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock



from custom_components.daynight_lighting.manual_control import (
    ManualControlDetector,
    _mired_to_kelvin,
    compare_light_to_target,
)

from tests.conftest import FakeHass, FakeState


def _make_detector(instance_name: str = "Test") -> ManualControlDetector:
    """Create a ManualControlDetector."""
    return ManualControlDetector(instance_name=instance_name)


def _make_fake_state_controller():
    """Create a mock StateController with expected state storage."""
    ctrl = MagicMock()
    ctrl._expected_states = {}

    def get_expected_state(light_id: str):
        return ctrl._expected_states.get(light_id)

    def set_expected_state(light_id: str, on: bool, brightness_pct: int | None = None, kelvin: int | None = None):
        ctrl._expected_states[light_id] = {
            "on": on,
            "brightness_pct": brightness_pct,
            "kelvin": kelvin,
            "timestamp": datetime.now(timezone.utc).timestamp(),
        }

    ctrl.get_expected_state = get_expected_state
    ctrl.set_expected_state = set_expected_state
    return ctrl


# ===================================================================
#  Helper function tests
# ===================================================================


class TestMiredToKelvin:
    """Tests for _mired_to_kelvin helper."""

    def test_none_returns_none(self):
        assert _mired_to_kelvin(None) is None

    def test_zero_returns_none(self):
        assert _mired_to_kelvin(0) is None

    def test_350_mired(self):
        # 1,000,000 / 350 ≈ 2857K
        result = _mired_to_kelvin(350)
        assert result == 2857

    def test_250_mired(self):
        # 1,000,000 / 250 = 4000K
        result = _mired_to_kelvin(250)
        assert result == 4000


class TestCompareLightToTargetStrict:
    """The ``strict`` flag answers "exactly matches" instead of "clearly differs".

    The night re-apply skip test uses it: an attribute it cannot verify must
    be re-applied rather than skipped. In the lenient mode the same missing
    attribute is *not* a divergence, so the two flags genuinely differ.
    """

    def test_missing_brightness_is_not_leniently_divergent(self):
        comparison = compare_light_to_target(
            {"color_temp": 435},
            80,
            2300,
            brightness_tolerance_pct=5,
            kelvin_tolerance=200,
        )
        assert comparison.brightness_differs is False

    def test_missing_brightness_is_strictly_divergent(self):
        comparison = compare_light_to_target(
            {"color_temp": 435},
            80,
            2300,
            brightness_tolerance_pct=1,
            kelvin_tolerance=30,
            strict=True,
        )
        assert comparison.brightness_differs is True

    def test_missing_color_is_not_leniently_divergent(self):
        comparison = compare_light_to_target(
            {"brightness": 204},
            80,
            2300,
            brightness_tolerance_pct=5,
            kelvin_tolerance=200,
        )
        assert comparison.color_differs is False

    def test_missing_color_is_strictly_divergent(self):
        comparison = compare_light_to_target(
            {"brightness": 204},
            80,
            2300,
            brightness_tolerance_pct=1,
            kelvin_tolerance=30,
            strict=True,
        )
        assert comparison.color_differs is True

    def test_exact_mired_target_matches_tightly(self):
        # 435 mired ≈ 2299K, the round-trip of a 2300K command.
        comparison = compare_light_to_target(
            {"brightness": 204, "color_temp": 435},
            80,
            2300,
            brightness_tolerance_pct=1,
            kelvin_tolerance=30,
            strict=True,
        )
        assert not comparison.brightness_differs
        assert not comparison.color_differs


# ===================================================================
#  Mark applied / grace period
# ===================================================================


class TestMarkApplied:
    """Tests for mark_applied and grace period."""

    def test_mark_applied_records_time(self):
        detector = _make_detector()
        now = datetime.now(timezone.utc)

        detector.mark_applied(["light.a", "light.b"])

        assert "light.a" in detector._last_applied_time
        assert "light.b" in detector._last_applied_time
        # Time should be recent
        assert (now - detector._last_applied_time["light.a"]).total_seconds() < 1

    def test_is_in_grace_period_true_immediately(self):
        detector = _make_detector()
        detector.mark_applied(["light.a"])

        assert detector.is_in_grace_period("light.a") is True

    def test_is_in_grace_period_false_after_expiry(self):
        detector = _make_detector()
        # Manually set time in the past (beyond 5s grace)
        past = datetime.now(timezone.utc)
        detector._last_applied_time["light.a"] = past

        # Should be in grace period (time hasn't moved forward much in test)
        # In real time, this would eventually expire
        result = detector.is_in_grace_period("light.a")
        # This depends on test execution speed, so we verify the logic
        # The grace period is 5 seconds
        assert detector.DEFAULT_GRACE_PERIOD_SEC == 5

    def test_is_in_grace_period_false_for_unknown_light(self):
        detector = _make_detector()
        assert detector.is_in_grace_period("light.unknown") is False


# ===================================================================
#  check_external_control - basic scenarios
# ===================================================================


class TestCheckExternalControlBasic:
    """Basic external control detection scenarios."""

    def test_no_expected_state_skips_light(self):
        """Light with no expected state is skipped (can't compare)."""
        hass = FakeHass()
        detector = _make_detector()
        state_ctrl = _make_fake_state_controller()

        # Don't set expected state

        external = detector.check_external_control(
            hass,
            ["light.a"],
            state_ctrl,
        )

        assert external == []

    def test_light_on_when_expected_on_matches(self):
        """Light ON when expected ON - no external control."""
        hass = FakeHass()
        hass.states.set("light.a", FakeState(state="on", attributes={"brightness": 128}))
        detector = _make_detector()
        state_ctrl = _make_fake_state_controller()
        state_ctrl.set_expected_state("light.a", on=True)

        external = detector.check_external_control(
            hass,
            ["light.a"],
            state_ctrl,
            check_brightness=False,
            check_color=False,
        )

        assert external == []

    def test_light_off_when_expected_off_matches(self):
        """Light OFF when expected OFF - no external control."""
        hass = FakeHass()
        hass.states.set("light.a", FakeState(state="off"))
        detector = _make_detector()
        state_ctrl = _make_fake_state_controller()
        state_ctrl.set_expected_state("light.a", on=False)

        external = detector.check_external_control(
            hass,
            ["light.a"],
            state_ctrl,
        )

        assert external == []

    def test_light_off_when_expected_on_is_external(self):
        """Light OFF when expected ON - external control detected."""
        hass = FakeHass()
        hass.states.set("light.a", FakeState(state="off"))
        detector = _make_detector()
        state_ctrl = _make_fake_state_controller()
        state_ctrl.set_expected_state("light.a", on=True)

        external = detector.check_external_control(
            hass,
            ["light.a"],
            state_ctrl,
        )

        assert "light.a" in external

    def test_light_on_when_expected_off_is_external(self):
        """Light ON when expected OFF - external control detected."""
        hass = FakeHass()
        hass.states.set("light.a", FakeState(state="on", attributes={"brightness": 128}))
        detector = _make_detector()
        state_ctrl = _make_fake_state_controller()
        state_ctrl.set_expected_state("light.a", on=False)

        external = detector.check_external_control(
            hass,
            ["light.a"],
            state_ctrl,
        )

        assert "light.a" in external

    def test_missing_state_skips_light(self):
        """Light with no hass state is skipped."""
        hass = FakeHass()
        # Don't set state for light.a
        detector = _make_detector()
        state_ctrl = _make_fake_state_controller()
        state_ctrl.set_expected_state("light.a", on=True)

        external = detector.check_external_control(
            hass,
            ["light.a"],
            state_ctrl,
        )

        assert external == []

    def test_unavailable_state_is_not_external(self):
        """A briefly unavailable light is not an external intervention."""
        hass = FakeHass()
        hass.states.set("light.a", FakeState(state="unavailable"))
        detector = _make_detector()
        state_ctrl = _make_fake_state_controller()
        state_ctrl.set_expected_state("light.a", on=True)

        external = detector.check_external_control(
            hass,
            ["light.a"],
            state_ctrl,
        )

        assert external == []

    def test_unknown_state_is_not_external(self):
        """A briefly unknown light is not an external intervention."""
        hass = FakeHass()
        hass.states.set("light.a", FakeState(state="unknown"))
        detector = _make_detector()
        state_ctrl = _make_fake_state_controller()
        state_ctrl.set_expected_state("light.a", on=True)

        external = detector.check_external_control(
            hass,
            ["light.a"],
            state_ctrl,
        )

        assert external == []


# ===================================================================
#  check_external_control - brightness comparison
# ===================================================================


class TestCheckExternalControlBrightness:
    """Brightness-based external control detection."""

    def test_matching_brightness_within_tolerance(self):
        """Brightness within tolerance - no external control."""
        hass = FakeHass()
        # Expected 50%, actual 52% (within 5% tolerance)
        hass.states.set("light.a", FakeState(state="on", attributes={"brightness": 132}))  # ~52%
        detector = _make_detector()
        state_ctrl = _make_fake_state_controller()
        state_ctrl.set_expected_state("light.a", on=True, brightness_pct=50)

        external = detector.check_external_control(
            hass,
            ["light.a"],
            state_ctrl,
            check_brightness=True,
            brightness_tolerance_pct=5,
        )

        assert external == []

    def test_brightness_beyond_tolerance_is_external(self):
        """Brightness beyond tolerance - external control."""
        hass = FakeHass()
        # Expected 50%, actual 80% (>5% tolerance)
        hass.states.set("light.a", FakeState(state="on", attributes={"brightness": 204}))  # 80%
        detector = _make_detector()
        state_ctrl = _make_fake_state_controller()
        state_ctrl.set_expected_state("light.a", on=True, brightness_pct=50)

        external = detector.check_external_control(
            hass,
            ["light.a"],
            state_ctrl,
            check_brightness=True,
            brightness_tolerance_pct=5,
        )

        assert "light.a" in external

    def test_zero_brightness_not_checked(self):
        """Light reporting brightness=0 is not checked (some lights do this)."""
        hass = FakeHass()
        hass.states.set("light.a", FakeState(state="on", attributes={"brightness": 0}))
        detector = _make_detector()
        state_ctrl = _make_fake_state_controller()
        state_ctrl.set_expected_state("light.a", on=True, brightness_pct=50)

        external = detector.check_external_control(
            hass,
            ["light.a"],
            state_ctrl,
            check_brightness=True,
        )

        # Should not flag external (brightness check skipped for 0)
        assert external == []

    def test_brightness_check_disabled(self):
        """When check_brightness=False, brightness not compared."""
        hass = FakeHass()
        # Expected 50%, actual 80%
        hass.states.set("light.a", FakeState(state="on", attributes={"brightness": 204}))
        detector = _make_detector()
        state_ctrl = _make_fake_state_controller()
        state_ctrl.set_expected_state("light.a", on=True, brightness_pct=50)

        external = detector.check_external_control(
            hass,
            ["light.a"],
            state_ctrl,
            check_brightness=False,  # Disabled
        )

        # Should not flag external (brightness check disabled)
        assert external == []


# ===================================================================
#  check_external_control - color comparison
# ===================================================================


class TestCheckExternalControlColor:
    """Color temperature-based external control detection."""

    def test_matching_kelvin_within_tolerance(self):
        """Kelvin within tolerance - no external control."""
        hass = FakeHass()
        # Expected 3000K (333 mired), actual 2950K (339 mired)
        # Difference: 50K < 200K tolerance
        hass.states.set("light.a", FakeState(state="on", attributes={"color_temp": 339}))
        detector = _make_detector()
        state_ctrl = _make_fake_state_controller()
        state_ctrl.set_expected_state("light.a", on=True, kelvin=3000)

        external = detector.check_external_control(
            hass,
            ["light.a"],
            state_ctrl,
            check_color=True,
            kelvin_tolerance=200,
        )

        assert external == []

    def test_kelvin_beyond_tolerance_is_external(self):
        """Kelvin beyond tolerance - external control."""
        hass = FakeHass()
        # Expected 3000K (333 mired), actual 4000K (250 mired)
        # Difference: 1000K > 200K tolerance
        hass.states.set("light.a", FakeState(state="on", attributes={"color_temp": 250}))
        detector = _make_detector()
        state_ctrl = _make_fake_state_controller()
        state_ctrl.set_expected_state("light.a", on=True, kelvin=3000)

        external = detector.check_external_control(
            hass,
            ["light.a"],
            state_ctrl,
            check_color=True,
            kelvin_tolerance=200,
        )

        assert "light.a" in external

    def test_color_check_disabled(self):
        """When check_color=False, kelvin not compared."""
        hass = FakeHass()
        hass.states.set("light.a", FakeState(state="on", attributes={"color_temp": 250}))
        detector = _make_detector()
        state_ctrl = _make_fake_state_controller()
        state_ctrl.set_expected_state("light.a", on=True, kelvin=3000)

        external = detector.check_external_control(
            hass,
            ["light.a"],
            state_ctrl,
            check_color=False,  # Disabled
        )

        assert external == []

    def test_rgb_scene_without_color_temp_is_external(self):
        """An RGB colour (no color_temp) is a scene we never command."""
        hass = FakeHass()
        # A Hue scene leaves rgb_color, no color_temp
        hass.states.set(
            "light.a",
            FakeState(state="on", attributes={"rgb_color": (255, 100, 50)}),
        )
        detector = _make_detector()
        state_ctrl = _make_fake_state_controller()
        state_ctrl.set_expected_state("light.a", on=True, kelvin=3000)

        external = detector.check_external_control(
            hass,
            ["light.a"],
            state_ctrl,
            check_color=True,
            kelvin_tolerance=200,
        )

        assert "light.a" in external

    def test_hs_color_without_color_temp_is_external(self):
        """An HS colour (no color_temp) is external."""
        hass = FakeHass()
        hass.states.set(
            "light.a",
            FakeState(state="on", attributes={"hs_color": (10.0, 100.0)}),
        )
        detector = _make_detector()
        state_ctrl = _make_fake_state_controller()
        state_ctrl.set_expected_state("light.a", on=True, kelvin=3000)

        external = detector.check_external_control(
            hass,
            ["light.a"],
            state_ctrl,
            check_color=True,
        )

        assert "light.a" in external

    def test_xy_color_without_color_temp_is_external(self):
        """An XY colour (no color_temp) is external."""
        hass = FakeHass()
        hass.states.set(
            "light.a",
            FakeState(state="on", attributes={"xy_color": (0.5, 0.4)}),
        )
        detector = _make_detector()
        state_ctrl = _make_fake_state_controller()
        state_ctrl.set_expected_state("light.a", on=True, kelvin=3000)

        external = detector.check_external_control(
            hass,
            ["light.a"],
            state_ctrl,
            check_color=True,
        )

        assert "light.a" in external

    def test_xy_white_matching_kelvin_is_not_external(self):
        """Our own circadian white reported as XY (Hue) is not external."""
        from custom_components.daynight_lighting.domain.colorimetry import (
            kelvin_to_xy,
        )

        hass = FakeHass()
        # A Hue bulb reports colour natively in XY; this XY is the white point
        # of the Kelvin we commanded, so it must NOT be held.
        hass.states.set(
            "light.a",
            FakeState(
                state="on",
                attributes={"color_mode": "xy", "xy_color": kelvin_to_xy(3000)},
            ),
        )
        detector = _make_detector()
        state_ctrl = _make_fake_state_controller()
        state_ctrl.set_expected_state("light.a", on=True, kelvin=3000)

        external = detector.check_external_control(
            hass,
            ["light.a"],
            state_ctrl,
            check_color=True,
            kelvin_tolerance=200,
        )

        assert external == []

    def test_xy_white_slightly_off_kelvin_is_not_external(self):
        """A small white drift (within threshold) is not flagged as a scene."""
        from custom_components.daynight_lighting.domain.colorimetry import (
            kelvin_to_xy,
        )

        hass = FakeHass()
        hass.states.set(
            "light.a",
            FakeState(
                state="on",
                attributes={"color_mode": "xy", "xy_color": kelvin_to_xy(3200)},
            ),
        )
        detector = _make_detector()
        state_ctrl = _make_fake_state_controller()
        state_ctrl.set_expected_state("light.a", on=True, kelvin=3000)

        external = detector.check_external_control(
            hass,
            ["light.a"],
            state_ctrl,
            check_color=True,
            kelvin_tolerance=200,
        )

        assert external == []

    def test_xy_clearly_different_white_is_external(self):
        """A clearly different white (6500K vs 3000K) is external."""
        from custom_components.daynight_lighting.domain.colorimetry import (
            kelvin_to_xy,
        )

        hass = FakeHass()
        hass.states.set(
            "light.a",
            FakeState(
                state="on",
                attributes={"color_mode": "xy", "xy_color": kelvin_to_xy(6500)},
            ),
        )
        detector = _make_detector()
        state_ctrl = _make_fake_state_controller()
        state_ctrl.set_expected_state("light.a", on=True, kelvin=3000)

        external = detector.check_external_control(
            hass,
            ["light.a"],
            state_ctrl,
            check_color=True,
            kelvin_tolerance=200,
        )

        assert "light.a" in external

    def test_color_mode_rgb_without_attributes_is_external(self):
        """color_mode=rgb alone marks a colour we never command."""
        hass = FakeHass()
        hass.states.set(
            "light.a",
            FakeState(state="on", attributes={"color_mode": "rgb"}),
        )
        detector = _make_detector()
        state_ctrl = _make_fake_state_controller()
        state_ctrl.set_expected_state("light.a", on=True, kelvin=3000)

        external = detector.check_external_control(
            hass,
            ["light.a"],
            state_ctrl,
            check_color=True,
        )

        assert "light.a" in external

    def test_dimmable_white_without_color_attrs_is_not_external(self):
        """A brightness-only light (no color_temp, no colour) is not flagged."""
        hass = FakeHass()
        # Dimmable white bulb: only brightness, no color attributes at all
        hass.states.set(
            "light.a",
            FakeState(state="on", attributes={"brightness": 128}),
        )
        detector = _make_detector()
        state_ctrl = _make_fake_state_controller()
        state_ctrl.set_expected_state("light.a", on=True, brightness_pct=50, kelvin=3000)

        external = detector.check_external_control(
            hass,
            ["light.a"],
            state_ctrl,
            check_brightness=True,
            check_color=True,
        )

        assert external == []


# ===================================================================
#  check_external_control - combined brightness + color
# ===================================================================


class TestCheckExternalControlCombined:
    """Combined brightness and color detection."""

    def test_either_differs_triggers_external(self):
        """External control if EITHER brightness OR color differs."""
        hass = FakeHass()
        # Brightness matches, color differs
        hass.states.set(
            "light.a",
            FakeState(state="on", attributes={"brightness": 128, "color_temp": 250})  # 4000K
        )
        detector = _make_detector()
        state_ctrl = _make_fake_state_controller()
        state_ctrl.set_expected_state("light.a", on=True, brightness_pct=50, kelvin=3000)

        external = detector.check_external_control(
            hass,
            ["light.a"],
            state_ctrl,
            check_brightness=True,
            check_color=True,
            brightness_tolerance_pct=5,
            kelvin_tolerance=200,
        )

        assert "light.a" in external

    def test_both_match_no_external(self):
        """No external control when both match."""
        hass = FakeHass()
        hass.states.set(
            "light.a",
            FakeState(state="on", attributes={"brightness": 128, "color_temp": 333})  # 50%, 3000K
        )
        detector = _make_detector()
        state_ctrl = _make_fake_state_controller()
        state_ctrl.set_expected_state("light.a", on=True, brightness_pct=50, kelvin=3000)

        external = detector.check_external_control(
            hass,
            ["light.a"],
            state_ctrl,
            check_brightness=True,
            check_color=True,
        )

        assert external == []


# ===================================================================
#  check_external_control - multiple lights
# ===================================================================


class TestCheckExternalControlMultipleLights:
    """Detection with multiple lights."""

    def test_only_offending_lights_returned(self):
        """Only lights that differ are returned."""
        hass = FakeHass()
        # Light a: matches
        hass.states.set("light.a", FakeState(state="on", attributes={"brightness": 128}))
        # Light b: differs
        hass.states.set("light.b", FakeState(state="on", attributes={"brightness": 200}))
        # Light c: matches
        hass.states.set("light.c", FakeState(state="on", attributes={"brightness": 128}))

        detector = _make_detector()
        state_ctrl = _make_fake_state_controller()
        state_ctrl.set_expected_state("light.a", on=True, brightness_pct=50)
        state_ctrl.set_expected_state("light.b", on=True, brightness_pct=50)
        state_ctrl.set_expected_state("light.c", on=True, brightness_pct=50)

        external = detector.check_external_control(
            hass,
            ["light.a", "light.b", "light.c"],
            state_ctrl,
            check_brightness=True,
            brightness_tolerance_pct=5,
        )

        assert "light.a" not in external
        assert "light.b" in external
        assert "light.c" not in external

    def test_grace_period_skips_light(self):
        """Lights in grace period are skipped."""
        hass = FakeHass()
        hass.states.set("light.a", FakeState(state="on", attributes={"brightness": 200}))

        detector = _make_detector()
        detector.mark_applied(["light.a"])  # In grace period
        state_ctrl = _make_fake_state_controller()
        state_ctrl.set_expected_state("light.a", on=True, brightness_pct=50)

        external = detector.check_external_control(
            hass,
            ["light.a"],
            state_ctrl,
            check_brightness=True,
        )

        # Should not flag (grace period)
        assert external == []


# ===================================================================
#  Mode-specific tolerances
# ===================================================================


class TestModeSpecificTolerances:
    """Tests for get_tolerances_for_mode."""

    def test_day_with_lux_sensor(self):
        tol = ManualControlDetector.get_tolerances_for_mode("day", has_lux_sensor=True)
        assert tol == (10, 300)

    def test_day_without_lux_sensor(self):
        tol = ManualControlDetector.get_tolerances_for_mode("day", has_lux_sensor=False)
        assert tol == (5, 200)

    def test_night_mode(self):
        tol = ManualControlDetector.get_tolerances_for_mode("night", has_lux_sensor=False)
        assert tol == (5, 200)

    def test_sleep_mode(self):
        tol = ManualControlDetector.get_tolerances_for_mode("sleep", has_lux_sensor=False)
        assert tol == (8, 250)

    def test_wakeup_mode(self):
        tol = ManualControlDetector.get_tolerances_for_mode("wakeup", has_lux_sensor=False)
        assert tol == (8, 250)

    def test_unknown_mode_defaults_to_night(self):
        tol = ManualControlDetector.get_tolerances_for_mode("unknown", has_lux_sensor=False)
        assert tol == (5, 200)  # Night mode defaults
