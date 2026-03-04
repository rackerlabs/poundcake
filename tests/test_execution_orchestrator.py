from __future__ import annotations

from dataclasses import dataclass

import pytest

from api.services.execution_adapters.base import ExecutionAdapter
from api.services.execution_adapters.registry import ExecutionAdapterRegistry
from api.services.execution_orchestrator import ExecutionOrchestrator
from api.services.execution_types import ExecutionContext, ExecutionResult


@dataclass
class _DummyAdapter(ExecutionAdapter):
    engine: str
    results: list[ExecutionResult]
    validation_error: str | None = None

    def validate(self, _ctx: ExecutionContext) -> str | None:
        return self.validation_error

    async def execute_once(self, _ctx: ExecutionContext) -> ExecutionResult:
        if self.results:
            return self.results.pop(0)
        return ExecutionResult(engine=self.engine, status="failed", error_message="exhausted")


@pytest.mark.asyncio
async def test_orchestrator_retries_retryable_failures_until_success():
    registry = ExecutionAdapterRegistry()
    registry.register(
        _DummyAdapter(
            engine="stackstorm",
            results=[
                ExecutionResult(engine="stackstorm", status="failed", retryable=True),
                ExecutionResult(
                    engine="stackstorm", status="succeeded", execution_ref="exec-1", raw={"id": "1"}
                ),
            ],
        )
    )
    orchestrator = ExecutionOrchestrator(registry)

    result = await orchestrator.execute(
        ExecutionContext(
            engine="stackstorm",
            execution_target="poundcake.workflow",
            req_id="REQ-1",
            retry_count=2,
            retry_delay=0,
        )
    )

    assert result.status == "succeeded"
    assert result.execution_ref == "exec-1"
    assert result.attempts == 2


@pytest.mark.asyncio
async def test_orchestrator_stops_after_retry_exhaustion():
    registry = ExecutionAdapterRegistry()
    registry.register(
        _DummyAdapter(
            engine="bakery",
            results=[
                ExecutionResult(
                    engine="bakery", status="failed", retryable=True, error_message="boom"
                ),
                ExecutionResult(
                    engine="bakery", status="failed", retryable=True, error_message="boom"
                ),
            ],
        )
    )
    orchestrator = ExecutionOrchestrator(registry)

    result = await orchestrator.execute(
        ExecutionContext(
            engine="bakery",
            execution_target="core",
            req_id="REQ-2",
            retry_count=1,
            retry_delay=0,
        )
    )

    assert result.status == "failed"
    assert result.attempts == 2


@pytest.mark.asyncio
async def test_orchestrator_returns_failure_for_unknown_engine():
    orchestrator = ExecutionOrchestrator(ExecutionAdapterRegistry())
    result = await orchestrator.execute(
        ExecutionContext(engine="native", execution_target="noop", req_id="REQ-3")
    )
    assert result.status == "failed"
    assert "Unsupported execution_engine" in str(result.error_message)
