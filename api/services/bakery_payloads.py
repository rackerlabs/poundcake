"""Shared helpers for resolving Bakery comms payload templates."""

from __future__ import annotations

from copy import deepcopy
from typing import Any


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    return {}


def deep_merge_payload(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    """Merge dictionaries recursively while replacing scalars and lists."""
    merged = deepcopy(base)
    for key, value in overlay.items():
        if isinstance(merged.get(key), dict) and isinstance(value, dict):
            merged[key] = deep_merge_payload(merged[key], value)
            continue
        merged[key] = deepcopy(value)
    return merged


def resolve_bakery_payload(
    payload: dict[str, Any] | None,
    *,
    runtime_overlay: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Resolve a Bakery payload template into a final outbound payload."""
    raw_payload = _as_dict(payload)
    template = _as_dict(raw_payload.get("template"))
    default_overlay = {key: deepcopy(value) for key, value in raw_payload.items() if key != "template"}

    resolved = deep_merge_payload(template, default_overlay)
    if runtime_overlay:
        resolved = deep_merge_payload(resolved, _as_dict(runtime_overlay))
    return resolved


def is_template_payload(payload: dict[str, Any] | None) -> bool:
    return isinstance(_as_dict(payload).get("template"), dict)
