"""The three transition options and the cap on tick transitions.

The options matrix in ``docs/BEHAVIOUR.md`` promises that each of the three
transition settings reaches ``light.turn_on``/``turn_off`` as the ``transition``
field.  These characterisation tests pin the mapping: which option feeds which
context, and that a tick transition can never outlast the tick interval (a
longer tick transition would make every update overlap the next one).
"""

from __future__ import annotations

from custom_components.daynight_lighting.const import (
    CONF_INITIAL_TRANSITION_SECONDS,
    CONF_MODE_TRANSITION_SECONDS,
    CONF_TRANSITION_SECONDS,
    MAX_TICK_TRANSITION_SECONDS,
)


def test_defaults_are_instant(make_switch):
    """Without configuration every context is instant (0 seconds)."""
    switch, *_ = make_switch()

    assert switch._get_transition() == 0
    assert switch._get_transition("initial") == 0
    assert switch._get_transition("mode") == 0


def test_tick_transition_uses_the_configured_value(make_switch):
    """The regular tick transition comes from ``transition_seconds``."""
    switch, *_ = make_switch({CONF_TRANSITION_SECONDS: 20})

    assert switch._get_transition() == 20


def test_tick_transition_is_capped_below_the_tick_interval(make_switch):
    """A tick transition may not reach into the next tick."""
    switch, *_ = make_switch({CONF_TRANSITION_SECONDS: 9999})

    assert switch._get_transition() == MAX_TICK_TRANSITION_SECONDS


def test_initial_transition_is_not_capped(make_switch):
    """The first turn-on may take as long as the user configured."""
    switch, *_ = make_switch({CONF_INITIAL_TRANSITION_SECONDS: 60})

    assert switch._get_transition("initial") == 60


def test_mode_transition_is_not_capped(make_switch):
    """A day↔night change may take as long as the user configured."""
    switch, *_ = make_switch({CONF_MODE_TRANSITION_SECONDS: 90})

    assert switch._get_transition("mode") == 90
