from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from api.models.models import Order, OrderCommunication
from api.services import order_communications


def _make_order(order_id: int = 1) -> Order:
    now = datetime.now(timezone.utc)
    order = Order(
        id=order_id,
        req_id="REQ-1",
        fingerprint="fp-1",
        alert_status="firing",
        processing_status="processing",
        is_active=True,
        remediation_outcome="pending",
        clear_timeout_sec=None,
        clear_deadline_at=None,
        clear_timed_out_at=None,
        auto_close_eligible=False,
        alert_group_name="group",
        severity="critical",
        instance="host1",
        counter=1,
        bakery_ticket_state=None,
        bakery_permanent_failure=False,
        bakery_last_error=None,
        labels={"alertname": "DiskFull"},
        annotations={},
        raw_data={},
        starts_at=now,
        ends_at=None,
        created_at=now,
        updated_at=now,
    )
    order.communications = []
    return order


def _make_communication(
    *,
    order: Order,
    execution_target: str = "rackspace_core",
    destination_target: str = "primary",
    bakery_ticket_id: str | None = "comm-1",
    remote_state: str | None = "open",
) -> OrderCommunication:
    now = datetime.now(timezone.utc)
    communication = OrderCommunication(
        id=1,
        order_id=order.id,
        execution_target=execution_target,
        destination_target=destination_target,
        bakery_ticket_id=bakery_ticket_id,
        bakery_operation_id=None,
        lifecycle_state="pending",
        remote_state=remote_state,
        writable=True,
        reopenable=False,
        last_error=None,
        created_at=now,
        updated_at=now,
    )
    order.communications = [communication]
    return communication


@pytest.mark.asyncio
async def test_apply_execution_result_refreshes_remote_state_after_successful_close(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order = _make_order()
    communication = _make_communication(order=order, remote_state="open")
    db = SimpleNamespace(flush=AsyncMock())

    monkeypatch.setattr(
        order_communications,
        "load_order_with_communications",
        AsyncMock(return_value=order),
    )
    get_communication = AsyncMock(return_value={"state": "confirmed_solved"})
    monkeypatch.setattr(order_communications, "get_communication", get_communication)

    await order_communications.apply_execution_result(
        db,
        order_id=order.id,
        execution_target=communication.execution_target,
        destination_target=communication.destination_target,
        operation="close",
        execution_ref="op-close-1",
        status="succeeded",
        result_payload={"status": "succeeded", "provider_response": {"success": True}},
    )

    get_communication.assert_awaited_once_with("comm-1")
    assert communication.lifecycle_state == "succeeded"
    assert communication.bakery_operation_id == "op-close-1"
    assert communication.remote_state == "confirmed_solved"
    assert communication.writable is True
    assert communication.reopenable is True
    assert order.bakery_ticket_state == "confirmed_solved"
    db.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_apply_execution_result_refreshes_remote_state_for_new_successful_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order = _make_order(order_id=2)
    communication = _make_communication(
        order=order,
        execution_target="discord",
        destination_target="discord",
        bakery_ticket_id=None,
        remote_state=None,
    )
    db = SimpleNamespace(flush=AsyncMock())

    monkeypatch.setattr(
        order_communications,
        "load_order_with_communications",
        AsyncMock(return_value=order),
    )
    get_communication = AsyncMock(return_value={"state": "open"})
    monkeypatch.setattr(order_communications, "get_communication", get_communication)

    await order_communications.apply_execution_result(
        db,
        order_id=order.id,
        execution_target=communication.execution_target,
        destination_target=communication.destination_target,
        operation="open",
        execution_ref="op-open-1",
        status="succeeded",
        result_payload={"status": "succeeded"},
        context_updates={"bakery_ticket_id": "comm-2"},
    )

    get_communication.assert_awaited_once_with("comm-2")
    assert communication.bakery_ticket_id == "comm-2"
    assert communication.bakery_operation_id == "op-open-1"
    assert communication.remote_state == "open"
    assert communication.writable is True
    assert communication.reopenable is False
    assert order.bakery_ticket_state is None
    db.flush.assert_awaited_once()
