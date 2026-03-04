"""Registry for execution engine adapters."""

from __future__ import annotations

from api.services.execution_adapters.base import ExecutionAdapter


class ExecutionAdapterRegistry:
    """Resolve adapters by normalized execution engine name."""

    def __init__(self) -> None:
        self._adapters: dict[str, ExecutionAdapter] = {}

    def register(self, adapter: ExecutionAdapter) -> None:
        self._adapters[adapter.engine.lower()] = adapter

    def get(self, engine: str) -> ExecutionAdapter | None:
        return self._adapters.get((engine or "").strip().lower())
