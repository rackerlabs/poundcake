"""Environment value utilities shared across services."""

from __future__ import annotations


def env_to_bool(value: str | None, default: bool = False) -> bool:
    """Parse a boolean-like environment variable string."""
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}
