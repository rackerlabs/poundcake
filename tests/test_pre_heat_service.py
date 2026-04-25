#  ____                        _  ____      _
# |  _ \ ___  _   _ _ __   __| |/ ___|__ _| | _____
# | |_) / _ \| | | | '_ \ / _` | |   / _` | |/ / _ \
# |  __/ (_) | |_| | | | | (_| | |__| (_| |   <  __/
# |_|   \___/ \__,_|_| |_|\__,_|\____\__,_|_|\_\___|
#
"""Unit tests for pre_heat service."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, Mock, patch

import pytest

from api.models.models import Order
from api.services.pre_heat import pre_heat


class ScalarResult:
    def __init__(self, first=None, items=None):
        self._first = first
        self._items = items if items is not None else ([] if first is None else [first])

    def scalars(self):
        return self

    def first(self):
        return self._first

    def all(self):
        return self._items

    def scalar(self):
        return self._first


class DummyBegin:
    async def __aenter__(self):
        return None

    async def __aexit__(self, exc_type, exc, tb):
        return False


def _make_order(status: str = "new") -> Order:
    now = datetime.now(timezone.utc)
    return Order(
        id=1,
        req_id="REQ-1",
        fingerprint="fp-1",
        alert_status="firing",
        processing_status=status,
        is_active=True,
        alert_group_name="group",
        severity="high",
        instance="host1",
        counter=1,
        bakery_ticket_state=None,
        bakery_permanent_failure=False,
        bakery_last_error=None,
        labels={"alertname": "Test"},
        annotations={},
        raw_data={},
        starts_at=now,
        ends_at=None,
        created_at=now,
        updated_at=now,
    )


@pytest.mark.asyncio
async def test_pre_heat_no_alerts():
    db = AsyncMock()
    db.begin = Mock(return_value=DummyBegin())

    with patch("api.services.pre_heat.find_first_matching_suppression", new_callable=AsyncMock):
        result = await pre_heat({"alerts": []}, db=db, req_id="REQ-1")
    assert result["status"] == "no_alerts"
    assert result["results"] == []


@pytest.mark.asyncio
async def test_pre_heat_firing_creates_order():
    db = AsyncMock()
    db.begin = Mock(return_value=DummyBegin())
    db.execute = AsyncMock(return_value=ScalarResult(first=None))
    created: list[Order] = []

    def _add(order: Order) -> None:
        created.append(order)

    async def _flush() -> None:
        if created:
            created[-1].id = 123

    db.add = Mock(side_effect=_add)
    db.flush = AsyncMock(side_effect=_flush)

    payload = {
        "alerts": [
            {
                "status": "firing",
                "labels": {"alertname": "CPUHigh", "instance": "host1"},
                "annotations": {},
                "startsAt": "2026-02-10T00:00:00Z",
                "fingerprint": "fp-1",
            }
        ]
    }

    with patch(
        "api.services.pre_heat.find_first_matching_suppression",
        new=AsyncMock(return_value=None),
    ):
        result = await pre_heat(payload, db=db, req_id="REQ-1")
    assert result["status"] == "created"
    assert result["order_id"] == 123


@pytest.mark.asyncio
async def test_pre_heat_firing_increments_existing():
    existing = _make_order(status="processing")
    db = AsyncMock()
    db.begin = Mock(return_value=DummyBegin())
    db.execute = AsyncMock(return_value=ScalarResult(first=existing))

    payload = {
        "alerts": [
            {
                "status": "firing",
                "labels": {"alertname": "CPUHigh", "instance": "host1"},
                "annotations": {},
                "fingerprint": "fp-1",
            }
        ]
    }

    with patch(
        "api.services.pre_heat.find_first_matching_suppression",
        new=AsyncMock(return_value=None),
    ):
        result = await pre_heat(payload, db=db, req_id="REQ-1")
    assert result["status"] == "counter_incremented"
    assert result["order_id"] == existing.id


@pytest.mark.asyncio
async def test_pre_heat_watchdog_firing_records_heartbeat_without_order():
    db = AsyncMock()
    db.begin = Mock(return_value=DummyBegin())
    db.in_transaction = Mock(return_value=False)
    record = AsyncMock(
        return_value={
            "status": "watchdog_heartbeat_recorded",
            "order_id": None,
            "fingerprint": "watchdog-fp",
            "alert_name": "watchdog-warning",
            "alert_status": "firing",
        }
    )

    payload = {
        "alerts": [
            {
                "status": "firing",
                "labels": {
                    "alertname": "watchdog-warning",
                    "group_name": "watchdog",
                    "severity": "warning",
                },
                "annotations": {},
                "fingerprint": "watchdog-fp",
            }
        ]
    }

    with patch("api.services.pre_heat.record_watchdog_heartbeat", record):
        result = await pre_heat(payload, db=db, req_id="REQ-WATCHDOG")

    assert result["status"] == "watchdog_heartbeat_recorded"
    assert result["order_id"] is None
    db.execute.assert_not_called()
    record.assert_awaited_once()


@pytest.mark.asyncio
async def test_pre_heat_correlates_child_alert_to_active_root_order():
    parent = _make_order(status="waiting_clear")
    parent.labels = {
        "alertname": "kube-node-not-ready-warning",
        "correlation_key": "node/node-1",
        "correlation_scope": "node",
        "affected_node": "node-1",
        "root_cause": "true",
    }
    db = AsyncMock()
    db.begin = Mock(return_value=DummyBegin())
    db.execute = AsyncMock(side_effect=[ScalarResult(first=None), ScalarResult(items=[parent])])

    payload = {
        "alerts": [
            {
                "status": "firing",
                "labels": {
                    "alertname": "kube-pod-not-ready-warning",
                    "group_name": "kube-pod-not-ready",
                    "severity": "warning",
                    "correlation_key": "node/node-1",
                    "correlation_scope": "node",
                    "affected_node": "node-1",
                    "namespace": "openstack",
                    "pod": "nova-api-1",
                },
                "annotations": {"summary": "Pod is not ready"},
                "fingerprint": "child-fp",
                "startsAt": "2026-02-10T00:00:00Z",
            }
        ]
    }

    with patch(
        "api.services.pre_heat.find_first_matching_suppression",
        new=AsyncMock(return_value=None),
    ):
        result = await pre_heat(payload, db=db, req_id="REQ-1")

    assert result["status"] == "correlated_child"
    assert result["order_id"] == parent.id
    assert parent.counter == 2
    correlation = parent.raw_data["correlation"]
    assert correlation["child_count"] == 1
    assert correlation["active_child_count"] == 1
    assert correlation["affected_namespaces"] == ["openstack"]
    assert correlation["affected_workloads"] == ["openstack/nova-api-1"]
    assert correlation["child_counts_by_group"] == {"kube-pod-not-ready": 1}
    db.add.assert_not_called()


@pytest.mark.asyncio
async def test_pre_heat_updates_correlated_child_resolution_on_parent():
    parent = _make_order(status="waiting_clear")
    parent.labels = {
        "alertname": "kube-node-not-ready-warning",
        "correlation_key": "node/node-1",
        "correlation_scope": "node",
        "affected_node": "node-1",
        "root_cause": "true",
    }
    parent.raw_data = {
        "correlation": {
            "children": [
                {
                    "fingerprint": "child-fp",
                    "alert_name": "kube-pod-not-ready-warning",
                    "group_name": "kube-pod-not-ready",
                    "status": "firing",
                    "counter": 1,
                }
            ]
        }
    }
    db = AsyncMock()
    db.begin = Mock(return_value=DummyBegin())
    db.execute = AsyncMock(
        side_effect=[
            ScalarResult(first=None),
            ScalarResult(first=None),
            ScalarResult(items=[parent]),
        ]
    )

    payload = {
        "alerts": [
            {
                "status": "resolved",
                "labels": {
                    "alertname": "kube-pod-not-ready-warning",
                    "group_name": "kube-pod-not-ready",
                    "severity": "warning",
                    "correlation_key": "node/node-1",
                    "correlation_scope": "node",
                    "affected_node": "node-1",
                    "namespace": "openstack",
                    "pod": "nova-api-1",
                },
                "annotations": {"summary": "Pod is not ready"},
                "fingerprint": "child-fp",
                "endsAt": "2026-02-10T00:05:00Z",
            }
        ]
    }

    with patch(
        "api.services.pre_heat.find_first_matching_suppression",
        new=AsyncMock(return_value=None),
    ):
        result = await pre_heat(payload, db=db, req_id="REQ-1")

    assert result["status"] == "correlated_child"
    child = parent.raw_data["correlation"]["children"][0]
    assert child["status"] == "resolved"
    assert child["counter"] == 2
    assert parent.raw_data["correlation"]["active_child_count"] == 0


@pytest.mark.asyncio
async def test_pre_heat_resolved_routes_to_resolving_and_records_metric():
    existing = _make_order(status="new")
    db = AsyncMock()
    db.begin = Mock(return_value=DummyBegin())
    db.execute = AsyncMock(side_effect=[ScalarResult(first=existing), ScalarResult(first=None)])

    payload = {
        "alerts": [
            {
                "status": "resolved",
                "labels": {"alertname": "CPUHigh", "instance": "host1"},
                "annotations": {},
                "fingerprint": "fp-1",
                "endsAt": "2026-02-10T00:01:00Z",
            }
        ]
    }

    with (
        patch(
            "api.services.pre_heat.find_first_matching_suppression",
            new=AsyncMock(return_value=None),
        ),
        patch("api.services.pre_heat.record_order_resolved_before_dish_start") as record_metric,
    ):
        result = await pre_heat(payload, db=db, req_id="REQ-1")

    assert result["status"] == "resolved"
    assert existing.processing_status == "resolving"
    assert existing.is_active is True
    record_metric.assert_called_once()


@pytest.mark.asyncio
async def test_pre_heat_resolved_updates_latest_inactive_unresolved_order():
    existing = _make_order(status="complete")
    existing.is_active = False
    existing.alert_status = "firing"
    db = AsyncMock()
    db.begin = Mock(return_value=DummyBegin())
    db.execute = AsyncMock(
        side_effect=[
            ScalarResult(first=None),
            ScalarResult(first=existing),
            ScalarResult(first="complete"),
        ]
    )

    payload = {
        "alerts": [
            {
                "status": "resolved",
                "labels": {"alertname": "CPUHigh", "instance": "host1"},
                "annotations": {},
                "fingerprint": "fp-1",
                "endsAt": "2026-02-10T00:01:00Z",
            }
        ]
    }

    with (
        patch(
            "api.services.pre_heat.find_first_matching_suppression",
            new=AsyncMock(return_value=None),
        ),
        patch("api.services.pre_heat.record_order_resolved_before_dish_start") as record_metric,
    ):
        result = await pre_heat(payload, db=db, req_id="REQ-1")

    assert result["status"] == "resolved"
    assert result["order_id"] == existing.id
    assert existing.alert_status == "resolved"
    assert existing.processing_status == "complete"
    assert existing.is_active is False
    record_metric.assert_not_called()


@pytest.mark.asyncio
async def test_pre_heat_resolved_with_failed_order_keeps_order_terminal():
    existing = _make_order(status="failed")
    existing.bakery_ticket_id = "ticket-1"
    db = AsyncMock()
    db.begin = Mock(return_value=DummyBegin())
    db.execute = AsyncMock(side_effect=[ScalarResult(first=existing), ScalarResult(first="failed")])

    payload = {
        "alerts": [
            {
                "status": "resolved",
                "labels": {"alertname": "CPUHigh", "instance": "host1"},
                "annotations": {},
                "fingerprint": "fp-1",
                "endsAt": "2026-02-10T00:01:00Z",
            }
        ]
    }

    with patch(
        "api.services.pre_heat.find_first_matching_suppression",
        new=AsyncMock(return_value=None),
    ):
        result = await pre_heat(payload, db=db, req_id="REQ-1")

    assert result["status"] == "resolved"
    assert existing.processing_status == "failed"
    assert existing.is_active is False


@pytest.mark.asyncio
async def test_pre_heat_resolved_with_complete_order_keeps_order_terminal():
    existing = _make_order(status="complete")
    existing.is_active = False
    existing.bakery_ticket_id = "ticket-1"
    db = AsyncMock()
    db.begin = Mock(return_value=DummyBegin())
    db.execute = AsyncMock(
        side_effect=[
            ScalarResult(first=None),
            ScalarResult(first=existing),
            ScalarResult(first="complete"),
        ]
    )

    payload = {
        "alerts": [
            {
                "status": "resolved",
                "labels": {"alertname": "CPUHigh", "instance": "host1"},
                "annotations": {},
                "fingerprint": "fp-1",
                "endsAt": "2026-02-10T00:01:00Z",
            }
        ]
    }

    with patch(
        "api.services.pre_heat.find_first_matching_suppression",
        new=AsyncMock(return_value=None),
    ):
        result = await pre_heat(payload, db=db, req_id="REQ-1")

    assert result["status"] == "resolved"
    assert existing.processing_status == "complete"
    assert existing.is_active is False


@pytest.mark.asyncio
async def test_pre_heat_resolved_processing_order_moves_to_resolving():
    existing = _make_order(status="processing")
    existing.bakery_ticket_id = "ticket-1"
    db = AsyncMock()
    db.begin = Mock(return_value=DummyBegin())
    db.execute = AsyncMock(
        side_effect=[ScalarResult(first=existing), ScalarResult(first="complete")]
    )

    payload = {
        "alerts": [
            {
                "status": "resolved",
                "labels": {"alertname": "CPUHigh", "instance": "host1"},
                "annotations": {},
                "fingerprint": "fp-1",
                "endsAt": "2026-02-10T00:01:00Z",
            }
        ]
    }

    with (
        patch(
            "api.services.pre_heat.find_first_matching_suppression",
            new=AsyncMock(return_value=None),
        ),
    ):
        result = await pre_heat(payload, db=db, req_id="REQ-1")

    assert result["status"] == "resolved"
    assert existing.alert_status == "resolved"
    assert existing.processing_status == "resolving"
    assert existing.is_active is True


@pytest.mark.asyncio
async def test_pre_heat_resolved_keeps_canceled_order_terminal():
    existing = _make_order(status="canceled")
    existing.is_active = False
    db = AsyncMock()
    db.begin = Mock(return_value=DummyBegin())
    db.execute = AsyncMock(side_effect=[ScalarResult(first=existing), ScalarResult(first=None)])

    payload = {
        "alerts": [
            {
                "status": "resolved",
                "labels": {"alertname": "CPUHigh", "instance": "host1"},
                "annotations": {},
                "fingerprint": "fp-1",
                "endsAt": "2026-02-10T00:01:00Z",
            }
        ]
    }

    with patch(
        "api.services.pre_heat.find_first_matching_suppression",
        new=AsyncMock(return_value=None),
    ):
        result = await pre_heat(payload, db=db, req_id="REQ-1")

    assert result["status"] == "resolved"
    assert existing.processing_status == "canceled"
    assert existing.is_active is False


@pytest.mark.asyncio
async def test_pre_heat_firing_suppressed_does_not_create_order():
    db = AsyncMock()
    db.begin = Mock(return_value=DummyBegin())
    db.execute = AsyncMock(return_value=ScalarResult(first=None))
    db.flush = AsyncMock()

    suppression = Mock()
    suppression.id = 10

    payload = {
        "alerts": [
            {
                "status": "firing",
                "labels": {"alertname": "CPUHigh", "instance": "host1"},
                "annotations": {},
                "fingerprint": "fp-sup",
            }
        ]
    }

    with (
        patch(
            "api.services.pre_heat.find_first_matching_suppression",
            new=AsyncMock(return_value=suppression),
        ),
        patch(
            "api.services.pre_heat.save_suppressed_event",
            new=AsyncMock(),
        ) as save_event,
    ):
        result = await pre_heat(payload, db=db, req_id="REQ-SUP")

    assert result["status"] == "ignored_suppressed"
    assert result["results"][0]["suppression_id"] == 10
    save_event.assert_awaited_once()


@pytest.mark.asyncio
async def test_pre_heat_firing_does_not_copy_previous_ticket_state():
    db = AsyncMock()
    db.begin = Mock(return_value=DummyBegin())
    db.execute = AsyncMock(return_value=ScalarResult(first=None))
    created: list[Order] = []

    def _add(order: Order) -> None:
        created.append(order)

    async def _flush() -> None:
        if created:
            created[-1].id = 456

    db.add = Mock(side_effect=_add)
    db.flush = AsyncMock(side_effect=_flush)

    payload = {
        "alerts": [
            {
                "status": "firing",
                "labels": {"alertname": "CPUHigh", "instance": "host1"},
                "annotations": {},
                "fingerprint": "fp-1",
            }
        ]
    }

    with patch(
        "api.services.pre_heat.find_first_matching_suppression",
        new=AsyncMock(return_value=None),
    ):
        result = await pre_heat(payload, db=db, req_id="REQ-NEW")

    assert result["status"] == "created"
    assert result["order_id"] == 456
    assert created[0].bakery_ticket_id is None
    assert created[0].bakery_ticket_state is None
    assert created[0].remediation_outcome == "pending"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["resolving", "waiting_ticket_close"])
async def test_pre_heat_firing_reopens_active_order_for_redispatch(status: str):
    existing = _make_order(status=status)
    existing.alert_status = "resolved"
    existing.ends_at = datetime.now(timezone.utc)

    db = AsyncMock()
    db.begin = Mock(return_value=DummyBegin())
    db.execute = AsyncMock(return_value=ScalarResult(first=existing))

    payload = {
        "alerts": [
            {
                "status": "firing",
                "labels": {"alertname": "CPUHigh", "instance": "host1"},
                "annotations": {},
                "fingerprint": "fp-1",
            }
        ]
    }

    with patch(
        "api.services.pre_heat.find_first_matching_suppression",
        new=AsyncMock(return_value=None),
    ):
        result = await pre_heat(payload, db=db, req_id="REQ-REDISPATCH")

    assert result["status"] == "counter_incremented"
    assert db.execute.await_count == 2
