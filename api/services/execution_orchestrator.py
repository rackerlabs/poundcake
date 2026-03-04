"""Unified execution orchestrator for all execution engines."""

from __future__ import annotations

import asyncio

from api.core.logging import get_logger
from api.services.execution_adapters.bakery import BakeryExecutionAdapter
from api.services.execution_adapters.registry import ExecutionAdapterRegistry
from api.services.execution_adapters.stackstorm import StackStormExecutionAdapter
from api.services.execution_types import ExecutionContext, ExecutionResult
from api.services.stackstorm_service import get_action_manager

logger = get_logger(__name__)


class ExecutionOrchestrator:
    """Dispatches execution contexts to engine-specific adapters with shared retries."""

    def __init__(self, registry: ExecutionAdapterRegistry) -> None:
        self._registry = registry

    async def execute(self, ctx: ExecutionContext) -> ExecutionResult:
        adapter = self._registry.get(ctx.engine)
        if adapter is None:
            return ExecutionResult(
                engine=(ctx.engine or "").strip().lower() or "unknown",
                status="failed",
                error_message=f"Unsupported execution_engine: {ctx.engine}",
                retryable=False,
            )

        validation_error = adapter.validate(ctx)
        if validation_error:
            return ExecutionResult(
                engine=(ctx.engine or "").strip().lower(),
                status="failed",
                error_message=validation_error,
                retryable=False,
            )

        attempts = max(1, int(ctx.retry_count) + 1)
        for attempt in range(1, attempts + 1):
            result = await adapter.execute_once(ctx)
            result.attempts = attempt
            if result.status != "failed":
                return result
            if not result.retryable or attempt >= attempts:
                return result
            delay = max(0, int(ctx.retry_delay))
            logger.warning(
                "Execution attempt failed; retrying",
                extra={
                    "req_id": ctx.req_id,
                    "engine": ctx.engine,
                    "target": ctx.execution_target,
                    "attempt": attempt,
                    "max_attempts": attempts,
                    "delay_seconds": delay,
                },
            )
            if delay > 0:
                await asyncio.sleep(delay)

        return ExecutionResult(
            engine=(ctx.engine or "").strip().lower(),
            status="failed",
            error_message="Execution failed after retry loop",
            retryable=False,
            attempts=attempts,
        )


_orchestrator: ExecutionOrchestrator | None = None


def get_execution_orchestrator() -> ExecutionOrchestrator:
    global _orchestrator
    if _orchestrator is None:
        registry = ExecutionAdapterRegistry()
        registry.register(StackStormExecutionAdapter(get_action_manager()))
        registry.register(BakeryExecutionAdapter())
        _orchestrator = ExecutionOrchestrator(registry)
    return _orchestrator
