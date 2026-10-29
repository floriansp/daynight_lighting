"""Shared utilities for DayNight Lighting.

This module contains helper functions used across the integration to
eliminate code duplication and provide consistent behavior.
"""

from __future__ import annotations

import logging
from typing import Any

_LOGGER = logging.getLogger(__name__)


def extract_entity_id(options: dict[str, Any], key: str) -> str | None:
    """Extract a single entity_id from Home Assistant selector output.

    Handles various formats returned by different HA selector types:
    - str: "light.living_room"
    - list: ["light.living_room"] or ["light.living_room", "light.kitchen"]
    - dict: {"entity_id": "light.living_room"} or {"entity": "light.living_room"}
    - None: Returns None

    Args:
        options: Configuration options dictionary
        key: The key to look up in options

    Returns:
        A single entity_id string, or None if not found/invalid
    """
    raw = options.get(key)
    if raw is None:
        return None

    # Handle list - take first element
    if isinstance(raw, list):
        raw = raw[0] if raw else None

    if raw is None:
        return None

    # Handle dict formats from EntitySelector
    if isinstance(raw, dict):
        e = raw.get("entity_id") or raw.get("entity")
        raw = e[0] if isinstance(e, list) and e else e

    if raw is None:
        return None

    # Ensure it's a string
    if not isinstance(raw, str):
        return None

    # Strip whitespace
    stripped = raw.strip()
    if not stripped:
        return None

    # Validate entity_id format (must contain domain.object_id)
    if "." not in stripped:
        return None

    return stripped


def extract_entity_ids(options: dict[str, Any], key: str) -> list[str]:
    """Extract a list of entity_ids from a (multi-select) selector output.

    Handles every format HA entity selectors can produce, whether the field is
    configured for single or multiple selection::

        "light.a"                          -> ["light.a"]
        ["light.a", "light.b"]             -> ["light.a", "light.b"]
        {"entity_id": ["light.a", ...]}    -> ["light.a", ...]
        None                               -> []

    Invalid entries (non-strings, missing domain separator) are dropped so a
    malformed stored value never breaks the downstream sensor controllers.

    Args:
        options: Configuration options dictionary
        key: The key to look up in options

    Returns:
        A list of valid entity_id strings (possibly empty).
    """
    raw = options.get(key)
    if raw is None:
        return []

    # Handle dict formats from EntitySelector
    if isinstance(raw, dict):
        raw = raw.get("entity_id") or raw.get("entity")

    if raw is None:
        return []

    if isinstance(raw, str):
        raw = [raw]

    result: list[str] = []
    for item in raw:
        if not isinstance(item, str):
            continue
        stripped = item.strip()
        if stripped and "." in stripped:
            result.append(stripped)
    return result


def dedupe_entity_ids(entity_ids: list[str]) -> list[str]:
    """Deduplicate entity IDs case-insensitively, preserving order.

    Entity IDs are case-insensitive in Home Assistant, so ``light.A`` and
    ``light.a`` are the same light. The first occurrence wins and keeps its
    original casing; later duplicates (of any case) are dropped.

    Args:
        entity_ids: Entity IDs as stored in the configuration.

    Returns:
        The list with duplicates removed, in first-seen order.
    """
    seen: set[str] = set()
    result: list[str] = []
    for entity_id in entity_ids:
        key = entity_id.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(entity_id)
    return result


def parse_time_string(
    value: str | dict[str, Any] | None,
    default: tuple[int, int],
) -> tuple[int, int]:
    """Parse time from various input formats.

    Supports:
    - "HH:MM" or "HH:MM:SS" string format
    - dict with "hour" and "minute" keys
    - None (returns default)

    Args:
        value: The time value to parse
        default: Default (hour, minute) tuple if parsing fails

    Returns:
        (hour, minute) tuple with validated values (0-23, 0-59)
    """
    if value is None:
        return default

    # Handle dict format {"hour": 22, "minute": 0}
    if isinstance(value, dict):
        try:
            hour = int(value.get("hour", default[0]))
            minute = int(value.get("minute", default[1]))
            if 0 <= hour <= 23 and 0 <= minute <= 59:
                return (hour, minute)
        except (TypeError, ValueError):
            pass
        return default

    # Handle string format "HH:MM" or "HH:MM:SS"
    if not isinstance(value, str) or not value.strip():
        return default

    parts = value.strip().split(":")
    try:
        hour = int(parts[0])
        minute = int(parts[1]) if len(parts) > 1 else 0
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            return (hour, minute)
    except (ValueError, IndexError):
        pass

    return default
