"""Tests for forgetting the brightness damping memory.

Day mode only sends a brightness when it differs from the last one *it* sent.
That reference is what makes the regulation quiet, and it is also what gets
stale the moment somebody else changes a lamp: the integration keeps deciding
it is already at its target while the room sits at a stranger's brightness.

On a bright day this never resolves by itself, because the LUX-derived target
barely moves — and with LUX calibration it moves even less, since calibration
exists precisely to make the reading independent of our own lamps.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from custom_components.daynight_lighting.const import MODE_DAY, MODE_NIGHT
from tests.conftest import FakeState


@pytest.fixture
def day_switch(make_switch, fake_hass):
    """A switch in day mode whose LUX reading yields a stable target."""
    switch, *_ = make_switch(day_mode=True)
    fake_hass.states.set("sensor.lux", FakeState(state="50"))
    return switch


class TestTheDampingIsReal:
    """Guard the premise: without forgetting, the second apply is skipped."""

    def test_an_unchanged_target_is_skipped(self, day_switch, fake_hass):
        switch = day_switch
        day = switch._get_mode_handler(MODE_DAY)

        day.tick()
        assert fake_hass.services.async_call.call_count == 1

        fake_hass.services.async_call.reset_mock()
        day.tick()

        fake_hass.services.async_call.assert_not_called()


class TestForgettingBeatsTheDamping:
    """Releasing manual control must get the room back, unchanged target or not."""

    def test_release_applies_even_when_the_target_did_not_move(
        self, day_switch, fake_hass
    ):
        switch = day_switch
        day = switch._get_mode_handler(MODE_DAY)
        day.tick()
        fake_hass.services.async_call.reset_mock()

        switch.release_hold()

        fake_hass.services.async_call.assert_called_once()

    def test_colour_is_forgotten_too(self, day_switch):
        switch = day_switch
        day = switch._get_mode_handler(MODE_DAY)
        day.tick()
        assert day._last_applied_kelvin is not None

        day.forget_applied_values()

        assert day._last_applied_kelvin is None

    def test_every_mode_can_be_asked(self, day_switch):
        """The switch asks all handlers, so none may raise."""
        switch = day_switch

        switch._forget_applied_values()

        night = switch._get_mode_handler(MODE_NIGHT)
        assert night is not None  # built and asked without complaint


class TestTheFlappingFreezeSurvives:
    """A room that was oscillating is still oscillating afterwards."""

    def test_freeze_is_kept(self, day_switch):
        switch = day_switch
        day = switch._get_mode_handler(MODE_DAY)
        day.tick()
        reader = switch._illuminance
        freeze_until = datetime.now() + timedelta(minutes=5)
        reader._flapping_freeze_until = freeze_until

        day.forget_applied_values()

        assert reader._flapping_freeze_until == freeze_until
        assert reader.should_apply_brightness(99) is False

    def test_release_does_not_break_a_freeze(self, day_switch, fake_hass):
        switch = day_switch
        day = switch._get_mode_handler(MODE_DAY)
        day.tick()
        switch._illuminance._flapping_freeze_until = datetime.now() + timedelta(
            minutes=5
        )
        fake_hass.services.async_call.reset_mock()

        switch.release_hold()

        # Colour may still be sent, brightness may not
        for call in fake_hass.services.async_call.call_args_list:
            assert "brightness_pct" not in call[0][2]


class TestReaderLevel:
    """The reader's own contract."""

    def test_forget_clears_the_reference(self, day_switch):
        switch = day_switch
        reader = switch._illuminance
        reader.record_brightness_applied(60)

        reader.forget_applied_brightness()

        assert reader._last_applied_brightness_pct is None
        assert not reader._brightness_history
        assert reader.should_apply_brightness(60) is True

    def test_forget_twice_is_harmless(self, day_switch):
        switch = day_switch
        reader = switch._illuminance

        reader.forget_applied_brightness()
        reader.forget_applied_brightness()

        assert reader._last_applied_brightness_pct is None
