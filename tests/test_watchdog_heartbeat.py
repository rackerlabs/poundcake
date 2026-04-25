from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, Mock

import pytest

from api.models.models import Order, WatchdogHeartbeatState
from api.services.watchdog_heartbeat import (
    WATCHDOG_MISSING_ALERT_NAME,
    check_watchdog_heartbeat_once,
    is_watchdog_alert,
)


class ScalarResult:
    def __init__(self, first=None):
        self._first = first

    def scalars(self):
        return self

    def first(self):
        return self._first


class DummyBegin:
    async def __aenter__(self):
        return None

    async def __aexit__(self, exc_type, exc, tb):
        return False


def _make_missing_order() -> Order:
    now = datetime.now(timezone.utc)
    return Order(
        id=42,
        req_id="SYSTEM-WATCHDOG",
        fingerprint="poundcake:watchdog:missing",
        alert_status="firing",
        processing_status="new",
        is_active=True,
        remediation_outcome="pending",
        clear_timeout_sec=None,
        clear_deadline_at=None,
        clear_timed_out_at=None,
        auto_close_eligible=False,
        alert_group_name="poundcake-watchdog-missing",
        severity="critical",
        instance=None,
        counter=1,
        bakery_ticket_state=None,
        bakery_permanent_failure=False,
        bakery_last_error=None,
        labels={"alertname": WATCHDOG_MISSING_ALERT_NAME},
        annotations={},
        raw_data={},
        starts_at=now,
        ends_at=None,
        created_at=now,
        updated_at=now,
    )


def test_is_watchdog_alert_matches_group_or_alert_name():
    assert is_watchdog_alert({"group_name": "watchdog", "alertname": "anything"})
    assert is_watchdog_alert({"alertname": "Watchdog"})
    assert is_watchdog_alert({"alertname": "watchdog-warning"})
    assert not is_watchdog_alert({"alertname": WATCHDOG_MISSING_ALERT_NAME})


@pytest.mark.asyncio
async def test_check_watchdog_heartbeat_once_waits_for_initial_heartbeat_grace_period():
    db = AsyncMock()
    db.begin = Mock(return_value=DummyBegin())
    db.execute = AsyncMock(return_value=ScalarResult(first=None))
    created: list[WatchdogHeartbeatState] = []
    db.add = Mock(side_effect=created.append)

    result = await check_watchdog_heartbeat_once(db)

    assert result == {"status": "pending_initial_heartbeat", "order_id": None}
    assert created[0].heartbeat_key == "watchdog"
    assert created[0].missing_since is not None


@pytest.mark.asyncio
async def test_check_watchdog_heartbeat_once_creates_missing_incident():
    old = datetime.now(timezone.utc) - timedelta(seconds=600)
    state = WatchdogHeartbeatState(
        id=1,
        heartbeat_key="watchdog",
        last_seen_at=old,
        last_received_at=old,
        last_status="firing",
        created_at=old,
        updated_at=old,
    )
    db = AsyncMock()
    db.begin = Mock(return_value=DummyBegin())
    db.execute = AsyncMock(side_effect=[ScalarResult(first=state), ScalarResult(first=None)])
    created: list[Order] = []

    def _add(order: Order) -> None:
        created.append(order)

    async def _flush() -> None:
        created[-1].id = 100

    db.add = Mock(side_effect=_add)
    db.flush = AsyncMock(side_effect=_flush)

    result = await check_watchdog_heartbeat_once(db)

    assert result == {"status": "created", "order_id": 100}
    assert created[0].labels["alertname"] == WATCHDOG_MISSING_ALERT_NAME
    assert created[0].processing_status == "new"
    assert state.synthetic_order_id == 100


@pytest.mark.asyncio
async def test_check_watchdog_heartbeat_once_resolves_missing_incident_when_healthy():
    now = datetime.now(timezone.utc)
    state = WatchdogHeartbeatState(
        id=1,
        heartbeat_key="watchdog",
        last_seen_at=now,
        last_received_at=now,
        last_status="firing",
        created_at=now,
        updated_at=now,
    )
    order = _make_missing_order()
    db = AsyncMock()
    db.begin = Mock(return_value=DummyBegin())
    db.execute = AsyncMock(side_effect=[ScalarResult(first=state), ScalarResult(first=order)])

    result = await check_watchdog_heartbeat_once(db)

    assert result == {"status": "resolved", "order_id": order.id}
    assert order.alert_status == "resolved"
    assert order.processing_status == "resolving"
    assert order.ends_at is not None
