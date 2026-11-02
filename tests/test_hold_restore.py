"""Restored holds must be validated against reality on startup.

A ``detected`` hold survives a restart and only ends through an explicit
release, so one persisted before a restart could keep us off a light whose
intervention is long gone. Both load paths load, prune, re-validate, mark
applied and only then start listening. A lamp that has not reported yet is
judged when it does, against the expected state as it was at load.
"""

from __future__ import annotations

import logging
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.daynight_lighting.const import MODE_SLEEP
from custom_components.daynight_lighting.state_controller import (
    HOLD_REASON_DETECTED,
    HOLD_REASON_SERVICE,
    StateController,
)

from tests.conftest import (
    FakeState,
    capture_light_listener,
    light_listener,
    report_light_state,
)

# Day mode (sun above horizon, LUX sensor configured) tolerates 10% / 300K.
EXPECTED_BRIGHTNESS_PCT = 80
EXPECTED_KELVIN = 3000
MATCHING_ATTRS = {"brightness": 204, "color_temp": 333}  # 80% / ~3003K
DIVERGING_ATTRS = {"brightness": 51, "color_temp": 333}  # 20%


def _expected_state(
    *,
    on: bool = True,
    brightness_pct: int | None = EXPECTED_BRIGHTNESS_PCT,
    kelvin: int | None = EXPECTED_KELVIN,
    timestamp: float | None = None,
) -> dict:
    """Build one persisted expected-state entry."""
    return {
        "on": on,
        "brightness_pct": brightness_pct,
        "kelvin": kelvin,
        "timestamp": time.time() if timestamp is None else timestamp,
    }


def _seed(fake_store, holds: dict[str, str], expected: dict | None = None) -> None:
    """Put a persisted state into the fake store, as if from a restart."""
    fake_store._data = {
        "lights_we_control": sorted(holds),
        "held_lights": dict(holds),
        "expected_states": expected or {},
    }


async def _start(switch, fake_hass, *, path: str = "turn_on") -> None:
    """Run one of the two load paths with the given light states."""
    fake_hass.states.set("sensor.lux", FakeState(state="50"))
    switch._attr_is_on = False
    if path == "turn_on":
        await switch.async_turn_on()
    else:
        switch.async_get_last_state = AsyncMock(
            return_value=SimpleNamespace(state="on")
        )
        await switch.async_added_to_hass()


@pytest.mark.asyncio
async def test_matching_light_releases_detected_hold(make_switch, fake_hass, fake_store, caplog):
    """A hold whose light already matches the expected state protects nothing."""
    switch, *_ = make_switch(day_mode=True)
    _seed(fake_store, {"light.a": HOLD_REASON_DETECTED}, {"light.a": _expected_state()})
    fake_hass.states.set("light.a", FakeState(state="on", attributes=MATCHING_ATTRS))

    with caplog.at_level(logging.INFO, logger="custom_components.daynight_lighting.switch"):
        await _start(switch, fake_hass)

    assert not switch._state_ctrl.is_held("light.a")
    assert "matched expected state" in caplog.text


@pytest.mark.asyncio
async def test_brightness_divergence_keeps_detected_hold(make_switch, fake_hass, fake_store):
    """A brightness outside tolerance is still the intervention being held."""
    switch, *_ = make_switch(day_mode=True)
    _seed(fake_store, {"light.a": HOLD_REASON_DETECTED}, {"light.a": _expected_state()})
    fake_hass.states.set("light.a", FakeState(state="on", attributes=DIVERGING_ATTRS))

    await _start(switch, fake_hass)

    assert switch._state_ctrl.is_held("light.a")
    assert switch._state_ctrl.get_hold_reason("light.a") == HOLD_REASON_DETECTED


@pytest.mark.asyncio
async def test_light_off_while_expected_on_keeps_detected_hold(make_switch, fake_hass, fake_store):
    """The user deliberately keeps the room dark — that intent is protected."""
    switch, *_ = make_switch(day_mode=True)
    _seed(fake_store, {"light.a": HOLD_REASON_DETECTED}, {"light.a": _expected_state()})
    fake_hass.states.set("light.a", FakeState(state="off"))

    await _start(switch, fake_hass)

    assert switch._state_ctrl.is_held("light.a")


@pytest.mark.asyncio
async def test_unavailable_light_releases_detected_hold(make_switch, fake_hass, fake_store, caplog):
    """No evidence the intervention is still there — no hold."""
    switch, *_ = make_switch(day_mode=True)
    _seed(fake_store, {"light.a": HOLD_REASON_DETECTED}, {"light.a": _expected_state()})
    fake_hass.states.set("light.a", FakeState(state="unavailable"))

    with caplog.at_level(logging.INFO, logger="custom_components.daynight_lighting.switch"):
        await _start(switch, fake_hass)

    assert not switch._state_ctrl.is_held("light.a")
    assert "unavailable" in caplog.text


@pytest.mark.asyncio
async def test_missing_expected_state_releases_detected_hold(make_switch, fake_hass, fake_store, caplog):
    """Without an expected state there is nothing to compare against."""
    switch, *_ = make_switch(day_mode=True)
    _seed(fake_store, {"light.a": HOLD_REASON_DETECTED})
    fake_hass.states.set("light.a", FakeState(state="on", attributes=MATCHING_ATTRS))

    with caplog.at_level(logging.INFO, logger="custom_components.daynight_lighting.switch"):
        await _start(switch, fake_hass)

    assert not switch._state_ctrl.is_held("light.a")
    assert "no expected state" in caplog.text


@pytest.mark.asyncio
async def test_expected_off_and_light_off_releases_detected_hold(make_switch, fake_hass, fake_store):
    """Nothing is overridden: the expected state says off and the light is off."""
    switch, *_ = make_switch(day_mode=True)
    _seed(
        fake_store,
        {"light.a": HOLD_REASON_DETECTED},
        {"light.a": _expected_state(on=False, brightness_pct=None, kelvin=None)},
    )
    fake_hass.states.set("light.a", FakeState(state="off"))

    await _start(switch, fake_hass)

    assert not switch._state_ctrl.is_held("light.a")


@pytest.mark.asyncio
async def test_expected_off_but_light_on_keeps_detected_hold(make_switch, fake_hass, fake_store):
    """The light is on although it should be off — the intervention stands."""
    switch, *_ = make_switch(day_mode=True)
    _seed(
        fake_store,
        {"light.a": HOLD_REASON_DETECTED},
        {"light.a": _expected_state(on=False, brightness_pct=None, kelvin=None)},
    )
    fake_hass.states.set("light.a", FakeState(state="on", attributes=MATCHING_ATTRS))

    await _start(switch, fake_hass)

    assert switch._state_ctrl.is_held("light.a")


SCENARIOS = [
    ("matching", "on", MATCHING_ATTRS, True, False),
    ("brightness_divergence", "on", DIVERGING_ATTRS, True, True),
    ("expected_on_light_off", "off", {}, True, True),
    ("unavailable", "unavailable", {}, True, False),
    ("no_expected_state", "on", MATCHING_ATTRS, False, False),
]


@pytest.mark.parametrize(
    ("scenario", "light_state", "attributes", "has_expected", "detected_kept"),
    SCENARIOS,
    ids=[scenario[0] for scenario in SCENARIOS],
)
@pytest.mark.asyncio
async def test_service_hold_survives_every_case(
    make_switch,
    fake_hass,
    fake_store,
    scenario,
    light_state,
    attributes,
    has_expected,
    detected_kept,
):
    """An explicit service hold is user intent and must survive a restart."""
    switch, *_ = make_switch(day_mode=True)
    holds = {"light.a": HOLD_REASON_DETECTED, "light.b": HOLD_REASON_SERVICE}
    expected = {
        lid: _expected_state() for lid in holds
    } if has_expected else {}
    _seed(fake_store, holds, expected)
    for lid in holds:
        fake_hass.states.set(lid, FakeState(state=light_state, attributes=dict(attributes)))

    await _start(switch, fake_hass)

    assert switch._state_ctrl.is_held("light.a") is detected_kept
    assert switch._state_ctrl.is_held("light.b")
    assert switch._state_ctrl.get_hold_reason("light.b") == HOLD_REASON_SERVICE


@pytest.mark.parametrize("path", ["turn_on", "added_to_hass"])
@pytest.mark.asyncio
async def test_revalidation_runs_in_both_load_paths(make_switch, fake_hass, fake_store, path):
    """Both load paths must drop a hold that no longer protects anything."""
    switch, *_ = make_switch(day_mode=True)
    _seed(fake_store, {"light.a": HOLD_REASON_DETECTED}, {"light.a": _expected_state()})
    fake_hass.states.set("light.a", FakeState(state="on", attributes=MATCHING_ATTRS))

    spy = MagicMock(wraps=switch._revalidate_restored_holds)
    switch._revalidate_restored_holds = spy

    await _start(switch, fake_hass, path=path)

    spy.assert_called_once()
    assert not switch._state_ctrl.is_held("light.a")


class _ActiveSleepRamp:
    """Sleep handler stand-in that reports itself as ramping."""

    def is_sleep_active(self) -> bool:
        return True

    def tick(self) -> None:
        pass


@pytest.mark.asyncio
async def test_sleep_ramp_judges_on_off_only(make_switch, fake_hass, fake_store):
    """The ramp moves brightness legitimately, so it must not keep a hold."""
    switch, *_ = make_switch(day_mode=True)
    _seed(fake_store, {"light.a": HOLD_REASON_DETECTED}, {"light.a": _expected_state()})
    fake_hass.states.set("light.a", FakeState(state="on", attributes=DIVERGING_ATTRS))

    ramp = _ActiveSleepRamp()
    switch._get_mode_handler = lambda mode: ramp if mode == MODE_SLEEP else None

    await _start(switch, fake_hass)

    assert not switch._state_ctrl.is_held("light.a")


@pytest.mark.asyncio
async def test_expected_state_older_than_24h_is_dropped_on_load(fake_hass, fake_store):
    """Persisted expected states age out, so a reboot does not revive old ones."""
    fake_store._data = {
        "lights_we_control": [],
        "held_lights": {},
        "expected_states": {
            "light.old": _expected_state(timestamp=time.time() - 25 * 3600),
            "light.fresh": _expected_state(timestamp=time.time() - 23 * 3600),
        },
    }
    ctrl = StateController(fake_hass, "test_entry", "Test")
    ctrl._store = fake_store

    await ctrl.async_load()

    assert ctrl.get_expected_state("light.old") is None
    assert ctrl.get_expected_state("light.fresh") is not None


# ===================================================================
#  One ruler for both paths
# ===================================================================


@pytest.mark.asyncio
async def test_control_brightness_off_releases_a_brightness_divergence(
    make_switch, fake_hass, fake_store
):
    """The user said "don't manage brightness", so a brightness other than
    the expected one is not an intervention to step aside for."""
    switch, ctrl_brightness, _ = make_switch(day_mode=True)
    ctrl_brightness._attr_is_on = False
    _seed(fake_store, {"light.a": HOLD_REASON_DETECTED}, {"light.a": _expected_state()})
    fake_hass.states.set("light.a", FakeState(state="on", attributes=DIVERGING_ATTRS))

    await _start(switch, fake_hass)

    assert not switch._state_ctrl.is_held("light.a")


@pytest.mark.asyncio
async def test_detection_and_revalidation_share_one_ruler(
    make_switch, fake_hass, fake_store, monkeypatch
):
    """The same light, judged once when it changes and once at startup, must
    reach the same verdict — no path may use its own tolerances or axes."""
    switch, ctrl_brightness, _ = make_switch(day_mode=True)
    ctrl_brightness._attr_is_on = False
    captured = capture_light_listener(monkeypatch)

    await _start(switch, fake_hass)
    switch._first_tick_after_startup = False
    switch._manual_control_detector._last_applied_time.clear()

    # Event-driven: a brightness change we do not manage is not a detection.
    switch._state_ctrl.set_expected_state("light.a", on=True, brightness_pct=80, kelvin=EXPECTED_KELVIN)
    diverging = FakeState(state="on", attributes=DIVERGING_ATTRS)
    fake_hass.states.set("light.a", diverging)
    report_light_state(light_listener(captured), "light.a", diverging)
    assert not switch._state_ctrl.is_held("light.a")

    # Re-validation: the same divergence must not keep a restored hold either.
    switch._state_ctrl.set_hold(["light.a"], reason=HOLD_REASON_DETECTED)
    switch._revalidate_restored_holds()
    assert not switch._state_ctrl.is_held("light.a")


@pytest.mark.asyncio
async def test_a_colour_divergence_still_holds_when_brightness_is_off(
    make_switch, fake_hass, fake_store
):
    """Dropping the brightness axis must not drop the colour axis with it."""
    switch, ctrl_brightness, _ = make_switch(day_mode=True)
    ctrl_brightness._attr_is_on = False
    _seed(fake_store, {"light.a": HOLD_REASON_DETECTED}, {"light.a": _expected_state()})
    # 80% (matches) but a cool white where we expected 3000K.
    fake_hass.states.set(
        "light.a", FakeState(state="on", attributes={"brightness": 204, "color_temp": 200})
    )

    await _start(switch, fake_hass)

    assert switch._state_ctrl.is_held("light.a")


# ===================================================================
#  A lamp that has not reported yet (deferred re-validation)
# ===================================================================


@pytest.mark.asyncio
async def test_missing_light_state_keeps_the_hold_for_later(make_switch, fake_hass, fake_store):
    """No report from the lamp yet is not evidence that the hold is stale."""
    switch, *_ = make_switch(day_mode=True)
    _seed(fake_store, {"light.a": HOLD_REASON_DETECTED}, {"light.a": _expected_state()})

    await _start(switch, fake_hass)

    assert switch._state_ctrl.is_held("light.a")
    assert "light.a" in switch._pending_hold_checks


@pytest.mark.asyncio
async def test_deferred_check_releases_when_the_lamp_reports_matching(
    make_switch, fake_hass, fake_store, monkeypatch, caplog
):
    """The first report decides: a light at the expected state needs no hold."""
    switch, *_ = make_switch(day_mode=True)
    _seed(fake_store, {"light.a": HOLD_REASON_DETECTED}, {"light.a": _expected_state()})
    captured = capture_light_listener(monkeypatch)

    await _start(switch, fake_hass)
    assert switch._state_ctrl.is_held("light.a")

    state = FakeState(state="on", attributes=MATCHING_ATTRS)
    fake_hass.states.set("light.a", state)
    with caplog.at_level(logging.INFO, logger="custom_components.daynight_lighting.switch"):
        report_light_state(light_listener(captured), "light.a", state)

    assert not switch._state_ctrl.is_held("light.a")
    assert "light.a" not in switch._pending_hold_checks
    assert "matched expected state" in caplog.text


@pytest.mark.asyncio
async def test_deferred_check_keeps_when_the_lamp_reports_diverging(
    make_switch, fake_hass, fake_store, monkeypatch
):
    """The first report decides: a diverging light is the intervention."""
    switch, *_ = make_switch(day_mode=True)
    _seed(fake_store, {"light.a": HOLD_REASON_DETECTED}, {"light.a": _expected_state()})
    captured = capture_light_listener(monkeypatch)

    await _start(switch, fake_hass)
    assert switch._state_ctrl.is_held("light.a")

    state = FakeState(state="on", attributes=DIVERGING_ATTRS)
    fake_hass.states.set("light.a", state)
    report_light_state(light_listener(captured), "light.a", state)

    assert switch._state_ctrl.is_held("light.a")
    assert "light.a" not in switch._pending_hold_checks


@pytest.mark.asyncio
async def test_deferred_check_waits_for_a_real_state(make_switch, fake_hass, fake_store, monkeypatch):
    """An unavailable lamp is no evidence; the next real report decides."""
    switch, *_ = make_switch(day_mode=True)
    _seed(fake_store, {"light.a": HOLD_REASON_DETECTED}, {"light.a": _expected_state()})
    captured = capture_light_listener(monkeypatch)

    await _start(switch, fake_hass)
    listener = light_listener(captured)

    unavailable = FakeState(state="unavailable")
    fake_hass.states.set("light.a", unavailable)
    report_light_state(listener, "light.a", unavailable)

    assert switch._state_ctrl.is_held("light.a")
    assert "light.a" in switch._pending_hold_checks

    reported = FakeState(state="on", attributes=MATCHING_ATTRS)
    fake_hass.states.set("light.a", reported)
    report_light_state(listener, "light.a", reported)

    assert not switch._state_ctrl.is_held("light.a")


@pytest.mark.asyncio
async def test_deferred_check_uses_the_state_expected_at_load(
    make_switch, fake_hass, fake_store, monkeypatch
):
    """The startup tick rewrites the live expected state before the lamp reports,
    so the deferred check must use the snapshot taken at load."""
    switch, *_ = make_switch(day_mode=True)
    _seed(fake_store, {"light.a": HOLD_REASON_DETECTED}, {"light.a": _expected_state()})
    captured = capture_light_listener(monkeypatch)

    await _start(switch, fake_hass)
    # Our own command during the startup tick (the live record now says 20%).
    switch._state_ctrl.set_expected_state("light.a", on=True, brightness_pct=20, kelvin=EXPECTED_KELVIN)

    state = FakeState(state="on", attributes=DIVERGING_ATTRS)
    fake_hass.states.set("light.a", state)
    report_light_state(light_listener(captured), "light.a", state)

    # 20% matches the rewritten live record but not the 80% we expected at load.
    assert switch._state_ctrl.is_held("light.a")


@pytest.mark.asyncio
async def test_pending_snapshot_survives_an_in_place_edit_of_the_live_record(
    make_switch, fake_hass, fake_store, monkeypatch
):
    """The snapshot must be detached, not a reference into the state controller:
    an in-place edit of the live entry would otherwise silently re-target the
    deferred check."""
    switch, *_ = make_switch(day_mode=True)
    _seed(fake_store, {"light.a": HOLD_REASON_DETECTED}, {"light.a": _expected_state()})
    captured = capture_light_listener(monkeypatch)

    await _start(switch, fake_hass)
    # Bypass set_expected_state (which replaces the dict) and edit in place.
    switch._state_ctrl._expected_states["light.a"]["brightness_pct"] = 20

    state = FakeState(state="on", attributes=DIVERGING_ATTRS)
    fake_hass.states.set("light.a", state)
    report_light_state(light_listener(captured), "light.a", state)

    assert switch._state_ctrl.is_held("light.a")


@pytest.mark.asyncio
async def test_first_tick_judges_a_report_missed_by_the_listener(
    make_switch, fake_hass, fake_store
):
    """A report that lands between the load check and the subscription still counts."""
    switch, *_ = make_switch(day_mode=True)
    _seed(fake_store, {"light.a": HOLD_REASON_DETECTED}, {"light.a": _expected_state()})

    await _start(switch, fake_hass)
    assert switch._state_ctrl.is_held("light.a")

    fake_hass.states.set("light.a", FakeState(state="on", attributes=MATCHING_ATTRS))
    switch._first_tick_after_startup = True
    switch._handle_tick()

    assert not switch._state_ctrl.is_held("light.a")


@pytest.mark.asyncio
async def test_pending_check_is_dropped_when_the_hold_ends(
    make_switch, fake_hass, fake_store, monkeypatch, caplog
):
    """A hold released while its lamp was silent must not be judged later."""
    switch, *_ = make_switch(day_mode=True)
    _seed(fake_store, {"light.a": HOLD_REASON_DETECTED}, {"light.a": _expected_state()})
    captured = capture_light_listener(monkeypatch)

    await _start(switch, fake_hass)
    switch._state_ctrl.release_hold()

    state = FakeState(state="on", attributes=MATCHING_ATTRS)
    fake_hass.states.set("light.a", state)
    with caplog.at_level(logging.INFO, logger="custom_components.daynight_lighting.switch"):
        report_light_state(light_listener(captured), "light.a", state)

    assert "light.a" not in switch._pending_hold_checks
    assert "Restored hold released" not in caplog.text
