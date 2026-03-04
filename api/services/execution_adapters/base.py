"""Execution adapter interface for engine-specific execution backends."""

from __future__ import annotations

from abc import ABC, abstractmethod

from api.services.execution_types import ExecutionContext, ExecutionResult


class ExecutionAdapter(ABC):
    """Adapter contract implemented by each execution engine."""

    engine: str

    @abstractmethod
    def validate(self, ctx: ExecutionContext) -> str | None:
        """Validate engine-specific context before execution."""

    @abstractmethod
    async def execute_once(self, ctx: ExecutionContext) -> ExecutionResult:
        """Execute one attempt and return canonical execution result."""
