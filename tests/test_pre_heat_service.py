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
    def __init__(self, first=None):
        self._first = first

    def scalars(self):
        return self

    def first(self):
        return self._first

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
async def test_pre_heat_resolved_with_failed_order_leaves_ticket_open():
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

    with (
        patch("api.services.pre_heat.settings.bakery_enabled", True),
        patch(
            "api.services.pre_heat.find_first_matching_suppression",
            new=AsyncMock(return_value=None),
        ),
        patch("api.services.pre_heat.add_ticket_comment", new=AsyncMock()) as add_comment,
        patch("api.services.pre_heat.close_ticket", new=AsyncMock()) as close_ticket,
    ):
        result = await pre_heat(payload, db=db, req_id="REQ-1")

    assert result["status"] == "resolved"
    add_comment.assert_awaited_once()
    close_ticket.assert_not_awaited()
    assert existing.processing_status == "failed"
    assert existing.is_active is False


@pytest.mark.asyncio
async def test_pre_heat_resolved_with_complete_order_auto_closes_ticket():
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

    with (
        patch("api.services.pre_heat.settings.bakery_enabled", True),
        patch(
            "api.services.pre_heat.find_first_matching_suppression",
            new=AsyncMock(return_value=None),
        ),
        patch("api.services.pre_heat.add_ticket_comment", new=AsyncMock()) as add_comment,
        patch(
            "api.services.pre_heat.close_ticket",
            new=AsyncMock(return_value={"operation_id": "op-1"}),
        ) as close_ticket,
        patch(
            "api.services.pre_heat.poll_operation",
            new=AsyncMock(return_value={"status": "succeeded"}),
        ) as poll_operation,
    ):
        result = await pre_heat(payload, db=db, req_id="REQ-1")

    assert result["status"] == "resolved"
    add_comment.assert_awaited_once()
    close_ticket.assert_awaited_once()
    poll_operation.assert_awaited_once()
    assert existing.processing_status == "complete"
    assert existing.is_active is False


@pytest.mark.asyncio
async def test_pre_heat_resolved_keeps_processing_when_clear_note_fails():
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
        patch("api.services.pre_heat.settings.bakery_enabled", True),
        patch(
            "api.services.pre_heat.find_first_matching_suppression",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "api.services.pre_heat.add_ticket_comment",
            new=AsyncMock(side_effect=RuntimeError("comment failed")),
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
async def test_pre_heat_firing_reuses_previous_confirmed_solved_ticket():
    previous = _make_order(status="complete")
    previous.is_active = False
    previous.bakery_ticket_id = "ticket-123"
    previous.bakery_ticket_state = "confirmed_solved"
    previous.bakery_permanent_failure = False

    db = AsyncMock()
    db.begin = Mock(return_value=DummyBegin())
    db.execute = AsyncMock(side_effect=[ScalarResult(first=None), ScalarResult(first=previous)])
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

    with (
        patch("api.services.pre_heat.settings.bakery_enabled", True),
        patch(
            "api.services.pre_heat.find_first_matching_suppression",
            new=AsyncMock(return_value=None),
        ),
    ):
        result = await pre_heat(payload, db=db, req_id="REQ-NEW")

    assert result["status"] == "created"
    assert result["order_id"] == 456
    assert created[0].bakery_ticket_id == "ticket-123"
    assert created[0].bakery_ticket_state == "confirmed_solved"
