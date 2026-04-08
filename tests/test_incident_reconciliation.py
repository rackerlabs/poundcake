from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from api.models.models import Order, OrderCommunication
from api.services import incident_reconciliation


def _make_order(order_id: int = 1, status: str = "waiting_clear") -> Order:
    now = datetime.now(timezone.utc)
    order = Order(
        id=order_id,
        req_id="REQ-1",
        fingerprint="fp-1",
        alert_status="firing",
        processing_status=status,
        is_active=True,
        remediation_outcome="failed",
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
        labels={"alertname": "DiskFull", "group_name": "group", "instance": "host1"},
        annotations={"summary": "Disk full", "description": "PVC is full"},
        raw_data={},
        starts_at=now,
        ends_at=None,
        created_at=now,
        updated_at=now,
    )
    order.communications = []
    order.dishes = []
    return order


def _make_communication(
    *,
    order: Order,
    execution_target: str = "rackspace_core",
    destination_target: str = "primary",
    remote_state: str = "open",
    reopenable: bool = False,
) -> OrderCommunication:
    now = datetime.now(timezone.utc)
    communication = OrderCommunication(
        id=1,
        order_id=order.id,
        execution_target=execution_target,
        destination_target=destination_target,
        bakery_ticket_id="comm-1",
        bakery_operation_id=None,
        lifecycle_state="pending",
        remote_state=remote_state,
        writable=True,
        reopenable=reopenable,
        reconcile_metadata=None,
        last_error=None,
        created_at=now,
        updated_at=now,
    )
    order.communications = [communication]
    return communication


@pytest.mark.asyncio
async def test_reconcile_refire_waiting_ticket_close_resets_order_to_new(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order = _make_order(status="waiting_ticket_close")
    communication = _make_communication(order=order, remote_state="open")
    db = SimpleNamespace(flush=AsyncMock())

    monkeypatch.setattr(
        incident_reconciliation,
        "load_order_with_communications",
        AsyncMock(return_value=order),
    )
    monkeypatch.setattr(
        incident_reconciliation,
        "get_prometheus_client",
        lambda: SimpleNamespace(
            get_alerts=AsyncMock(
                return_value=[
                    {
                        "state": "firing",
                        "labels": {"alertname": "DiskFull", "group_name": "group", "instance": "host1"},
                    }
                ]
            )
        ),
    )
    monkeypatch.setattr(
        incident_reconciliation,
        "refresh_remote_state",
        AsyncMock(return_value=("open", True, False)),
    )

    result = await incident_reconciliation.reconcile_order(db, order_id=order.id, req_id="REQ-1")

    assert result["status"] == "reconciled"
    assert order.processing_status == "new"
    assert order.alert_status == "firing"
    assert "redispatch_firing" in result["actions"]
    assert communication.reconcile_metadata.get("last_clear_note_ticket_id") is None
    db.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_reconcile_waiting_ticket_close_notifies_once_and_then_completes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order = _make_order(status="waiting_ticket_close")
    order.alert_status = "resolved"
    order.ends_at = datetime.now(timezone.utc)
    _make_communication(order=order, remote_state="open")
    db = SimpleNamespace(flush=AsyncMock())

    refresh_states = iter([("open", True, False), ("open", True, False), ("closed", False, False)])

    async def _refresh(communication: OrderCommunication, **_kwargs):
        state, writable, reopenable = next(refresh_states)
        communication.remote_state = state
        communication.writable = writable
        communication.reopenable = reopenable
        return state, writable, reopenable

    notify = AsyncMock(return_value=SimpleNamespace(operation_id="op-note", communication_id="comm-1"))
    poll = AsyncMock(return_value=SimpleNamespace(status="succeeded", last_error=None))

    monkeypatch.setattr(
        incident_reconciliation,
        "load_order_with_communications",
        AsyncMock(return_value=order),
    )
    monkeypatch.setattr(
        incident_reconciliation,
        "get_prometheus_client",
        lambda: SimpleNamespace(get_alerts=AsyncMock(return_value=[])),
    )
    monkeypatch.setattr(incident_reconciliation, "refresh_remote_state", _refresh)
    monkeypatch.setattr(incident_reconciliation, "notify_communication", notify)
    monkeypatch.setattr(incident_reconciliation, "poll_operation", poll)

    first = await incident_reconciliation.reconcile_order(db, order_id=order.id, req_id="REQ-1")
    second = await incident_reconciliation.reconcile_order(db, order_id=order.id, req_id="REQ-1")

    assert first["status"] == "reconciled"
    assert order.processing_status == "complete"
    assert order.is_active is False
    assert notify.await_count == 1
    assert second["actions"] == ["complete_incident"]
    db.flush.assert_awaited()


@pytest.mark.asyncio
async def test_reconcile_waiting_clear_without_live_alert_moves_to_resolving(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order = _make_order(status="waiting_clear")
    _make_communication(order=order, remote_state="confirmed_solved", reopenable=True)
    db = SimpleNamespace(flush=AsyncMock())

    monkeypatch.setattr(
        incident_reconciliation,
        "load_order_with_communications",
        AsyncMock(return_value=order),
    )
    monkeypatch.setattr(
        incident_reconciliation,
        "get_prometheus_client",
        lambda: SimpleNamespace(get_alerts=AsyncMock(return_value=[])),
    )
    monkeypatch.setattr(
        incident_reconciliation,
        "refresh_remote_state",
        AsyncMock(return_value=("confirmed_solved", True, True)),
    )

    result = await incident_reconciliation.reconcile_order(db, order_id=order.id, req_id="REQ-1")

    assert result["status"] == "reconciled"
    assert order.processing_status == "resolving"
    assert order.alert_status == "resolved"
    assert "dispatch_resolving" in result["actions"]
    db.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_reconcile_firing_alert_reopens_closed_ticket(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order = _make_order(status="waiting_clear")
    communication = _make_communication(order=order, remote_state="confirmed_solved", reopenable=True)
    db = SimpleNamespace(flush=AsyncMock())

    update = AsyncMock(return_value=SimpleNamespace(operation_id="op-reopen", communication_id="comm-1"))
    notify = AsyncMock(return_value=SimpleNamespace(operation_id="op-note", communication_id="comm-1"))
    poll = AsyncMock(return_value=SimpleNamespace(status="succeeded", last_error=None))

    monkeypatch.setattr(
        incident_reconciliation,
        "load_order_with_communications",
        AsyncMock(return_value=order),
    )
    monkeypatch.setattr(
        incident_reconciliation,
        "get_prometheus_client",
        lambda: SimpleNamespace(
            get_alerts=AsyncMock(
                return_value=[
                    {
                        "state": "firing",
                        "labels": {"alertname": "DiskFull", "group_name": "group", "instance": "host1"},
                    }
                ]
            )
        ),
    )
    monkeypatch.setattr(
        incident_reconciliation,
        "refresh_remote_state",
        AsyncMock(side_effect=[("confirmed_solved", True, True), ("open", True, False)]),
    )
    monkeypatch.setattr(incident_reconciliation, "update_communication", update)
    monkeypatch.setattr(incident_reconciliation, "notify_communication", notify)
    monkeypatch.setattr(incident_reconciliation, "poll_operation", poll)

    result = await incident_reconciliation.reconcile_order(db, order_id=order.id, req_id="REQ-1")

    assert result["status"] == "reconciled"
    assert "reopened:rackspace_core:primary" in result["actions"]
    update.assert_awaited_once()
    notify.assert_awaited_once()
    assert communication.remote_state == "open"
    db.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_reconcile_defers_when_prometheus_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order = _make_order(status="waiting_clear")
    _make_communication(order=order, remote_state="open")
    db = SimpleNamespace(flush=AsyncMock())

    monkeypatch.setattr(
        incident_reconciliation,
        "load_order_with_communications",
        AsyncMock(return_value=order),
    )
    monkeypatch.setattr(
        incident_reconciliation,
        "get_prometheus_client",
        lambda: SimpleNamespace(get_alerts=AsyncMock(return_value=None)),
    )

    result = await incident_reconciliation.reconcile_order(db, order_id=order.id, req_id="REQ-1")

    assert result["status"] == "deferred"
    assert result["reason"] == "prometheus_unavailable"
    assert order.processing_status == "waiting_clear"
    db.flush.assert_not_awaited()
