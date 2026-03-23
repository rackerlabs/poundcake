from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from api.services.bakery_client import BakeryTicketAccepted, BakeryTicketOperation
from api.services.execution_adapters.bakery import BakeryExecutionAdapter
from api.services.execution_adapters.stackstorm import StackStormExecutionAdapter
from api.services.execution_types import ExecutionContext


@pytest.mark.asyncio
async def test_stackstorm_adapter_maps_running_status():
    manager = SimpleNamespace(
        _client=SimpleNamespace(
            execute_action=AsyncMock(
                return_value={"id": "st2-1", "status": "running", "result": {}}
            )
        )
    )
    adapter = StackStormExecutionAdapter(manager=manager)
    result = await adapter.execute_once(
        ExecutionContext(
            engine="stackstorm",
            execution_target="poundcake.test",
            execution_parameters={},
            req_id="REQ-ST2",
        )
    )
    assert result.status == "running"
    assert result.execution_ref == "st2-1"


@pytest.mark.asyncio
async def test_bakery_adapter_create_success_sets_context_update(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "api.services.execution_adapters.bakery.create_ticket_with_key",
        AsyncMock(
            return_value=BakeryTicketAccepted(
                ticket_id="INC-1",
                operation_id="op-1",
                action="create",
                status="succeeded",
                created_at="2026-03-19T00:00:00Z",
            )
        ),
    )
    monkeypatch.setattr(
        "api.services.execution_adapters.bakery.poll_operation",
        AsyncMock(
            return_value=BakeryTicketOperation(
                operation_id="op-1",
                ticket_id="INC-1",
                action="create",
                status="succeeded",
                attempt_count=1,
                max_attempts=5,
                created_at="2026-03-19T00:00:00Z",
                updated_at="2026-03-19T00:00:00Z",
            )
        ),
    )
    adapter = BakeryExecutionAdapter()
    result = await adapter.execute_once(
        ExecutionContext(
            engine="bakery",
            execution_target="core",
            execution_payload={"title": "A", "description": "B"},
            execution_parameters={"operation": "ticket_create"},
            req_id="REQ-BAKERY",
            context={"order_id": 10, "recipe_ingredient_id": 4},
        )
    )
    assert result.status == "succeeded"
    assert result.context_updates.get("bakery_ticket_id") == "INC-1"


@pytest.mark.asyncio
async def test_bakery_adapter_polls_operation_and_maps_failed_terminal_status(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(
        "api.services.execution_adapters.bakery.add_ticket_comment_with_key",
        AsyncMock(
            return_value=BakeryTicketAccepted(
                ticket_id="INC-2",
                operation_id="op-1",
                action="comment",
                status="queued",
                created_at="2026-03-19T00:00:00Z",
            )
        ),
    )
    monkeypatch.setattr(
        "api.services.execution_adapters.bakery.poll_operation",
        AsyncMock(
            return_value=BakeryTicketOperation(
                operation_id="op-1",
                ticket_id="INC-2",
                action="comment",
                status="dead_letter",
                attempt_count=1,
                max_attempts=5,
                last_error="unrecoverable",
                created_at="2026-03-19T00:00:00Z",
                updated_at="2026-03-19T00:00:00Z",
            )
        ),
    )
    adapter = BakeryExecutionAdapter()
    result = await adapter.execute_once(
        ExecutionContext(
            engine="bakery",
            execution_target="core",
            execution_payload={"comment": "c", "ticket_id": "INC-2"},
            execution_parameters={"operation": "ticket_comment"},
            req_id="REQ-BAKERY-2",
            context={"order_id": 1, "recipe_ingredient_id": 9},
        )
    )
    assert result.status == "failed"
    assert "unrecoverable" in str(result.error_message)
