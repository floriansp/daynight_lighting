"""V26: configurable, persisted per-light hold lifetime."""

from unittest.mock import AsyncMock

import pytest

from custom_components.daynight_lighting.config import DayNightConfig
from custom_components.daynight_lighting.const import (
    MODE_NIGHT,
    MODE_SLEEP,
    MODE_WAKEUP,
)
from custom_components.daynight_lighting.state_controller import StateController
from tests.test_hold_release import _day_switch, _hold_both, _pin_schedule, _motion
from tests.conftest import FakeState


@pytest.fixture
def clock(monkeypatch):
    now = [100000.0]
    monkeypatch.setattr(
        "custom_components.daynight_lighting.state_controller.time.time", lambda: now[0]
    )
    return now


def test_defaults_keep_todays_behaviour(make_switch, clock):
    cfg = DayNightConfig.from_ha_options({})
    assert cfg.detected_hold_survives_phase is True
    assert cfg.hold_timeout_min == 0
    switch, *_ = make_switch()
    switch._state_ctrl.set_hold(["light.a"], reason="detected")
    switch._clear_holds_entering(MODE_NIGHT)
    clock[0] += 999999
    assert switch._state_ctrl.expired_holds(0) == []
    assert switch._state_ctrl.is_held("light.a")


def test_detected_hold_ends_at_phase_change_when_configured(make_switch):
    switch, *_ = make_switch(options={"detected_hold_survives_phase": False})
    _hold_both(switch)
    switch._clear_holds_entering(MODE_NIGHT)
    assert not switch._state_ctrl.get_held_lights()


@pytest.mark.parametrize("reason", ["service", "detected"])
def test_hold_expires_after_the_timeout(make_switch, clock, reason):
    switch, *_ = make_switch(options={"hold_timeout_min": 2})
    ctrl = switch._state_ctrl
    ctrl.set_hold(["light.a"], reason=reason)
    clock[0] += 119
    assert ctrl.expired_holds(2) == []
    clock[0] += 1
    assert ctrl.expired_holds(2) == ["light.a"]
    switch._handle_tick()
    assert not ctrl.is_held("light.a")


def test_setting_again_extends_the_hold(make_switch, clock):
    switch, *_ = make_switch()
    ctrl = switch._state_ctrl
    ctrl.set_hold(["light.a"])
    clock[0] += 59
    ctrl.set_hold(["light.a"])
    clock[0] += 2
    assert ctrl.expired_holds(1) == []
    clock[0] += 58
    assert ctrl.expired_holds(1) == ["light.a"]


def test_expired_off_hold_turns_the_light_back_on(make_switch, monkeypatch, clock):
    switch = _day_switch(make_switch, monkeypatch)
    switch._config_entry.options["hold_timeout_min"] = 1
    switch.hass.states.set("light.a", FakeState(state="off"))
    switch._state_ctrl.set_hold(["light.a"])
    clock[0] += 61
    switch._handle_tick()
    assert switch._state_ctrl.get_expected_state("light.a")["on"] is True


def test_release_hold_works_when_holds_do_not_survive(make_switch):
    switch, *_ = make_switch(options={"detected_hold_survives_phase": False})
    _hold_both(switch)
    switch.release_hold()
    assert not switch._state_ctrl.get_held_lights()


@pytest.mark.asyncio
async def test_set_at_survives_a_restart(make_switch, fake_store, clock):
    switch, *_ = make_switch()
    switch._state_ctrl.set_hold(["light.a"])
    fake_store._data = switch._state_ctrl._data_to_save()
    clock[0] += 61
    restored = StateController(switch.hass, "restored")
    restored._store = fake_store
    await restored.async_load()
    assert restored.expired_holds(1) == ["light.a"]


@pytest.mark.asyncio
@pytest.mark.parametrize("held", [["light.a"], {"light.a": "detected"}])
async def test_legacy_hold_starts_its_timeout_at_load(
    make_switch, fake_store, clock, held
):
    switch, *_ = make_switch()
    fake_store._data = {"held_lights": held}
    await switch._state_ctrl.async_load()
    assert switch._state_ctrl.expired_holds(1) == []
    assert switch._state_ctrl._data_to_save()["hold_set_at"]["light.a"] == clock[0]
    clock[0] += 60
    assert switch._state_ctrl.expired_holds(1) == ["light.a"]


def test_expiry_leaves_the_dial_untouched(make_switch, monkeypatch, clock):
    switch = _day_switch(make_switch, monkeypatch)
    switch._config_entry.options["hold_timeout_min"] = 1
    from unittest.mock import patch

    _hold_both(switch)
    clock[0] += 61
    with patch.object(switch._dials, "reset_all") as reset:
        switch._release_expired_holds()
    reset.assert_not_called()


def test_expired_hold_is_adopted_like_the_button(make_switch, monkeypatch, clock):
    switch, *_ = make_switch(day_mode=False, options={"hold_timeout_min": 1})
    _pin_schedule(switch, MODE_NIGHT, monkeypatch)
    _motion(switch, False)
    _hold_both(switch)
    night = switch._get_mode_handler(MODE_NIGHT)
    monkeypatch.setattr(night, "_off_timer_result", lambda: ([], "none"))
    clock[0] += 61
    switch._release_expired_holds()
    for lid in switch.get_controlled_lights():
        expected = switch._state_ctrl.get_expected_state(lid)
        assert expected["on"] is True
        assert expected["brightness_pct"] == 40
        assert expected["kelvin"] == 3000
        assert expected["timestamp"] == clock[0]


def test_hold_expires_during_a_service_ramp(make_switch, monkeypatch, clock):
    switch, *_ = make_switch(options={"hold_timeout_min": 1})
    switch.start_sleep_mode_now()
    _hold_both(switch)
    clock[0] += 61
    switch._handle_tick()
    assert not switch._state_ctrl.get_held_lights()


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["turn_on", "restore"])
async def test_hold_that_expired_while_off_is_released_on_load(
    make_switch, fake_store, clock, path
):
    switch, *_ = make_switch(options={"hold_timeout_min": 1})
    switch._state_ctrl.set_hold(["light.a"])
    fake_store._data = switch._state_ctrl._data_to_save()
    clock[0] += 61
    if path == "turn_on":
        await switch.async_turn_on()
    else:
        from types import SimpleNamespace

        switch.async_get_last_state = AsyncMock(
            return_value=SimpleNamespace(state="on")
        )
        await switch.async_added_to_hass()
    assert not switch._state_ctrl.is_held("light.a")


@pytest.mark.parametrize("survive", [True, False])
@pytest.mark.parametrize("mode", [MODE_SLEEP, MODE_WAKEUP])
def test_ramp_start_still_ends_every_hold(make_switch, survive, mode):
    switch, *_ = make_switch(options={"detected_hold_survives_phase": survive})
    switch._state_ctrl.set_hold(["light.a"], reason="detected")
    switch._state_ctrl.set_hold(["light.b"], reason="service")
    switch._clear_holds_entering(mode)
    assert not switch._state_ctrl.get_held_lights()


def test_expiry_only_releases_elapsed_lights(make_switch, monkeypatch, clock):
    """A room-level reapply must leave a younger per-light hold alone."""
    switch = _day_switch(make_switch, monkeypatch)
    switch._config_entry.options["hold_timeout_min"] = 1
    switch._state_ctrl.set_hold(["light.a"])
    clock[0] += 30
    switch._state_ctrl.set_hold(["light.b"], reason="detected")
    clock[0] += 30
    switch._handle_tick()
    assert switch._state_ctrl.get_held_lights() == {"light.b"}
    assert switch._state_ctrl.get_expected_state("light.a")["on"] is True


def test_detected_intervention_renews_lifetime(make_switch, monkeypatch, clock):
    """A subsequent detected report refreshes an existing hold's deadline."""
    from tests.conftest import (
        capture_light_listener,
        light_listener,
        report_light_state,
    )

    switch = _day_switch(make_switch, monkeypatch)
    captured = capture_light_listener(monkeypatch)
    switch._start_listeners()
    listener = light_listener(captured)
    switch._manual_control_detector._last_applied_time.clear()
    changed = FakeState(state="off")
    switch.hass.states.set("light.a", changed)
    report_light_state(listener, "light.a", changed)
    assert switch._state_ctrl.is_held("light.a")
    clock[0] += 59
    changed = FakeState(state="on", attributes={"brightness": 10})
    switch.hass.states.set("light.a", changed)
    report_light_state(listener, "light.a", changed)
    clock[0] += 2
    assert switch._state_ctrl.expired_holds(1) == []
    clock[0] += 58
    assert switch._state_ctrl.expired_holds(1) == ["light.a"]
