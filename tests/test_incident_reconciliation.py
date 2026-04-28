from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from api.models.models import Dish, DishIngredient, Order, OrderCommunication
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


def _make_resolving_dish_step(
    *,
    execution_target: str = "rackspace_core",
    destination_target: str = "primary",
    payload: dict | None = None,
) -> DishIngredient:
    now = datetime.now(timezone.utc)
    return DishIngredient(
        id=10,
        dish_id=5,
        recipe_ingredient_id=None,
        task_key="step_1_fallback_close",
        deleted=False,
        deleted_at=None,
        execution_engine="bakery",
        execution_target=execution_target,
        destination_target=destination_target,
        execution_payload=payload or {},
        execution_parameters={"operation": "close"},
        execution_ref=None,
        expected_duration_sec=15,
        timeout_duration_sec=120,
        retry_count=1,
        retry_delay=5,
        on_failure="continue",
        attempt=0,
        execution_status="running",
        started_at=now,
        completed_at=None,
        canceled_at=None,
        result=None,
        error_message=None,
        created_at=now,
        updated_at=now,
    )


def _make_resolving_dish(*steps: DishIngredient) -> Dish:
    now = datetime.now(timezone.utc)
    dish = Dish(
        id=5,
        req_id="REQ-1",
        order_id=1,
        recipe_id=1,
        run_phase="resolving",
        processing_status="processing",
        expected_duration_sec=15,
        actual_duration_sec=None,
        execution_status=None,
        execution_ref=None,
        started_at=now,
        completed_at=None,
        result=None,
        error_message=None,
        retry_attempt=0,
        created_at=now,
        updated_at=now,
    )
    dish.dish_ingredients = list(steps)
    return dish


def test_alert_match_requires_same_hpa_when_hpa_label_is_present() -> None:
    order = _make_order()
    order.labels = {
        "alertname": "kube-hpa-maxed-out-warning",
        "group_name": "kube-hpa-maxed-out",
        "namespace": "openstack",
        "job": "kube-state-metrics",
        "service": "opentelemetry-kube-stack-kube-state-metrics",
        "instance": "10.236.13.166:8080",
        "severity": "warning",
        "horizontalpodautoscaler": "cinder-api",
    }

    assert not incident_reconciliation._alert_matches_order(
        order,
        {
            "state": "firing",
            "labels": {
                **order.labels,
                "horizontalpodautoscaler": "heat-engine",
            },
        },
    )
    assert incident_reconciliation._alert_matches_order(
        order,
        {"state": "firing", "labels": dict(order.labels)},
    )


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
                        "labels": {
                            "alertname": "DiskFull",
                            "group_name": "group",
                            "instance": "host1",
                        },
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

    notify = AsyncMock(
        return_value=SimpleNamespace(operation_id="op-note", communication_id="comm-1")
    )
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
    note_payload = notify.await_args.kwargs["payload"]
    assert "PoundCake did not remediate or validate a fix" in note_payload["comment"]
    assert "ticket remains open for human investigation" in note_payload["comment"]
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


def test_route_metadata_backfills_policy_keys_from_resolving_step() -> None:
    order = _make_order(status="resolving")
    communication = _make_communication(order=order, destination_target="primary")
    communication.reconcile_metadata = {
        "route_label": "Primary Core",
        "provider_config": {"account_number": "1234567"},
    }
    order.dishes = [
        _make_resolving_dish(
            _make_resolving_dish_step(
                payload={
                    "context": {
                        "route_label": "Primary Core",
                        "provider_config": {"account_number": "1234567"},
                        "poundcake_policy": {
                            "scope": "fallback",
                            "owner_key": "fallback",
                            "route_id": "core-primary",
                            "label": "Primary Core",
                            "execution_target": "rackspace_core",
                            "destination_target": "primary",
                            "provider_config": {"account_number": "1234567"},
                        },
                    }
                }
            )
        )
    ]

    metadata = incident_reconciliation._route_metadata(order, communication)

    assert metadata["scope"] == "fallback"
    assert metadata["owner_key"] == "fallback"
    assert metadata["route_id"] == "core-primary"
    assert metadata["route_label"] == "Primary Core"


@pytest.mark.asyncio
async def test_reconcile_resolved_order_skips_clear_note_while_resolving_step_is_active(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order = _make_order(status="resolving")
    order.alert_status = "resolved"
    order.ends_at = datetime.now(timezone.utc)
    _make_communication(order=order, remote_state="open")
    order.dishes = [_make_resolving_dish(_make_resolving_dish_step())]
    db = SimpleNamespace(flush=AsyncMock())

    notify = AsyncMock()

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
        AsyncMock(return_value=("open", True, False)),
    )
    monkeypatch.setattr(incident_reconciliation, "notify_communication", notify)

    result = await incident_reconciliation.reconcile_order(db, order_id=order.id, req_id="REQ-1")

    assert result["status"] == "reconciled"
    assert result["actions"] == []
    notify.assert_not_awaited()
    db.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_reconcile_resolved_order_skips_duplicate_clear_note_after_managed_notify(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order = _make_order(status="waiting_ticket_close")
    order.alert_status = "resolved"
    order.ends_at = datetime.now(timezone.utc)
    _make_communication(order=order, remote_state="open")
    step = _make_resolving_dish_step()
    step.execution_parameters = {"operation": "notify"}
    step.execution_status = "succeeded"
    step.completed_at = datetime.now(timezone.utc)
    order.dishes = [_make_resolving_dish(step)]
    order.dishes[0].processing_status = "complete"
    db = SimpleNamespace(flush=AsyncMock())

    notify = AsyncMock()

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
        AsyncMock(return_value=("open", True, False)),
    )
    monkeypatch.setattr(incident_reconciliation, "notify_communication", notify)

    result = await incident_reconciliation.reconcile_order(db, order_id=order.id, req_id="REQ-1")

    assert result["status"] == "reconciled"
    assert order.processing_status == "waiting_ticket_close"
    assert order.is_active is True
    notify.assert_not_awaited()
    db.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_reconcile_firing_alert_reopens_closed_ticket(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order = _make_order(status="waiting_clear")
    communication = _make_communication(
        order=order, remote_state="confirmed_solved", reopenable=True
    )
    db = SimpleNamespace(flush=AsyncMock())

    update = AsyncMock(
        return_value=SimpleNamespace(operation_id="op-reopen", communication_id="comm-1")
    )
    notify = AsyncMock(
        return_value=SimpleNamespace(operation_id="op-note", communication_id="comm-1")
    )
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
                        "labels": {
                            "alertname": "DiskFull",
                            "group_name": "group",
                            "instance": "host1",
                        },
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
