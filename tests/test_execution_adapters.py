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


@pytest.mark.asyncio
async def test_bakery_adapter_preserves_managed_route_context_when_reopening(
    monkeypatch: pytest.MonkeyPatch,
):
    update_mock = AsyncMock(
        return_value=BakeryTicketAccepted(
            ticket_id="INC-3",
            operation_id="op-reopen",
            action="update",
            status="queued",
            created_at="2026-03-19T00:00:00Z",
        )
    )
    notify_mock = AsyncMock(
        return_value=BakeryTicketAccepted(
            ticket_id="INC-3",
            operation_id="op-notify",
            action="notify",
            status="queued",
            created_at="2026-03-19T00:00:00Z",
        )
    )
    monkeypatch.setattr(
        "api.services.execution_adapters.bakery.update_ticket_with_key",
        update_mock,
    )
    monkeypatch.setattr(
        "api.services.execution_adapters.bakery.add_ticket_comment_with_key",
        notify_mock,
    )
    monkeypatch.setattr(
        "api.services.execution_adapters.bakery.poll_operation",
        AsyncMock(
            return_value=BakeryTicketOperation(
                operation_id="op-notify",
                ticket_id="INC-3",
                action="notify",
                status="succeeded",
                attempt_count=1,
                max_attempts=5,
                created_at="2026-03-19T00:00:00Z",
                updated_at="2026-03-19T00:00:00Z",
            )
        ),
    )
    managed_context = {
        "provider_type": "rackspace_core",
        "destination_target": "",
        "provider_config": {"account_number": "1234567"},
        "poundcake_policy": {
            "scope": "fallback",
            "owner_key": "fallback",
            "route_id": "core",
            "label": "Rackspace Core",
            "execution_target": "rackspace_core",
            "destination_target": "",
            "provider_config": {"account_number": "1234567"},
        },
    }

    adapter = BakeryExecutionAdapter()
    result = await adapter.execute_once(
        ExecutionContext(
            engine="bakery",
            execution_target="rackspace_core",
            execution_payload={
                "title": "Alert requires attention",
                "message": "No matching workflow is configured.",
                "context": managed_context,
            },
            execution_parameters={"operation": "open"},
            req_id="REQ-BAKERY-3",
            context={
                "order_id": 2,
                "recipe_ingredient_id": 10,
                "bakery_ticket_id": "INC-3",
                "communication_reuse_mode": "reopen",
            },
        )
    )

    assert result.status == "succeeded"
    reopen_payload = update_mock.await_args.kwargs["payload"]
    assert reopen_payload["state"] == "open"
    assert reopen_payload["context"]["poundcake_policy"]["route_id"] == "core"
    assert reopen_payload["context"]["attributes"]["status"] == "New"
    comment_payload = notify_mock.await_args.kwargs["payload"]
    assert comment_payload["comment"] == "No matching workflow is configured."
    assert comment_payload["context"]["poundcake_policy"]["route_id"] == "core"


@pytest.mark.asyncio
async def test_bakery_adapter_blocks_ticket_close_without_successful_remediation(
    monkeypatch: pytest.MonkeyPatch,
):
    close_mock = AsyncMock()
    monkeypatch.setattr(
        "api.services.execution_adapters.bakery.close_ticket_with_key",
        close_mock,
    )

    adapter = BakeryExecutionAdapter()
    result = await adapter.execute_once(
        ExecutionContext(
            engine="bakery",
            execution_target="rackspace_core",
            execution_payload={
                "ticket_id": "INC-4",
                "context": {
                    "_canonical": {
                        "order": {
                            "remediation_outcome": "none",
                            "auto_close_eligible": False,
                        }
                    }
                },
            },
            execution_parameters={"operation": "close"},
            req_id="REQ-BAKERY-4",
            context={"order_id": 4, "recipe_ingredient_id": 44},
        )
    )

    assert result.status == "succeeded"
    assert result.result == {
        "skipped": True,
        "reason": (
            "refusing to close communication because PoundCake did not record successful "
            "auto-remediation for this order"
        ),
    }
    close_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_bakery_adapter_allows_ticket_close_after_successful_remediation(
    monkeypatch: pytest.MonkeyPatch,
):
    close_mock = AsyncMock(
        return_value=BakeryTicketAccepted(
            ticket_id="INC-5",
            operation_id="op-close",
            action="close",
            status="queued",
            created_at="2026-03-19T00:00:00Z",
        )
    )
    monkeypatch.setattr(
        "api.services.execution_adapters.bakery.close_ticket_with_key",
        close_mock,
    )
    monkeypatch.setattr(
        "api.services.execution_adapters.bakery.poll_operation",
        AsyncMock(
            return_value=BakeryTicketOperation(
                operation_id="op-close",
                ticket_id="INC-5",
                action="close",
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
            execution_target="rackspace_core",
            execution_payload={
                "ticket_id": "INC-5",
                "context": {
                    "_canonical": {
                        "order": {
                            "remediation_outcome": "succeeded",
                            "auto_close_eligible": True,
                        }
                    }
                },
            },
            execution_parameters={"operation": "close"},
            req_id="REQ-BAKERY-5",
            context={"order_id": 5, "recipe_ingredient_id": 55},
        )
    )

    assert result.status == "succeeded"
    close_mock.assert_awaited_once()
