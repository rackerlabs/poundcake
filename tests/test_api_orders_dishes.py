#  ___                        _  ____      _
# |  _ \ ___  _   _ _ __   __| |/ ___|__ _| | _____
# | |_) / _ \| | | | '_ \ / _` | |   / _` | |/ / _ \
# |  __/ (_) | |_| | | | | (_| | |__| (_| |   <  __/
# |_|   \___/ \__,_|_| |_|\__,_|\____\__,_|_|\_\___|
#
"""Unit tests for orders and dishes API routes."""

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastapi.testclient import TestClient

from api.main import app
from api.models.models import Dish, Order


class ScalarResult:
    def __init__(self, first=None, all_=None):
        self._first = first
        self._all = all_ or []

    def scalars(self):
        return self

    def first(self):
        return self._first

    def all(self):
        return self._all

    def unique(self):
        return self


class _BeginContext:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def mock_db_session():
    with patch("api.core.database.SessionLocal") as mock_session:
        mock_db = AsyncMock()
        mock_db.begin = Mock(return_value=_BeginContext())
        mock_db.refresh = AsyncMock(return_value=None)
        mock_db.flush = AsyncMock(return_value=None)
        mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session.return_value.__aexit__ = AsyncMock(return_value=None)
        yield mock_db


def _make_order(order_id: int = 1, status: str = "new") -> Order:
    now = datetime.now(timezone.utc)
    return Order(
        id=order_id,
        req_id="REQ-1",
        fingerprint="fp-1",
        alert_status="firing",
        processing_status=status,
        is_active=True,
        alert_group_name="group",
        severity="high",
        instance="host1",
        counter=1,
        labels={"alertname": "Test"},
        annotations={},
        raw_data={},
        starts_at=now,
        ends_at=None,
        created_at=now,
        updated_at=now,
    )


def _make_dish(dish_id: int = 1, status: str = "new") -> Dish:
    now = datetime.now(timezone.utc)
    return Dish(
        id=dish_id,
        req_id="REQ-1",
        order_id=1,
        recipe_id=1,
        processing_status=status,
        expected_duration_sec=10,
        actual_duration_sec=None,
        status=None,
        workflow_execution_id=None,
        started_at=None,
        completed_at=None,
        result=None,
        error_message=None,
        retry_attempt=0,
        created_at=now,
        updated_at=now,
    )


def test_fetch_orders_returns_list(client, mock_db_session):
    order = _make_order()
    mock_db_session.execute = AsyncMock(return_value=ScalarResult(all_=[order]))

    response = client.get("/api/v1/orders?processing_status=new")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["id"] == order.id


def test_get_order_not_found(client, mock_db_session):
    mock_db_session.execute = AsyncMock(return_value=ScalarResult(first=None))

    response = client.get("/api/v1/orders/999")
    assert response.status_code == 404


def test_update_order_sets_is_active_false_on_terminal_status(client, mock_db_session):
    order = _make_order(status="processing")
    mock_db_session.execute = AsyncMock(return_value=ScalarResult(first=order))

    payload = {"processing_status": "complete"}
    response = client.put("/api/v1/orders/1", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body["processing_status"] == "complete"
    assert body["is_active"] is False


def test_update_order_rejects_terminal_to_terminal_transition(client, mock_db_session):
    order = _make_order(status="complete")
    mock_db_session.execute = AsyncMock(return_value=ScalarResult(first=order))

    payload = {"processing_status": "failed"}
    response = client.put("/api/v1/orders/1", json=payload)

    assert response.status_code == 409


def test_fetch_dishes_returns_list(client, mock_db_session):
    dish = _make_dish()
    mock_db_session.execute = AsyncMock(return_value=ScalarResult(all_=[dish]))

    response = client.get("/api/v1/dishes?processing_status=new")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["id"] == dish.id


def test_claim_dish_conflict(client, mock_db_session):
    mock_db_session.execute = AsyncMock(return_value=SimpleNamespace(rowcount=0))

    response = client.post("/api/v1/dishes/1/claim")
    assert response.status_code == 409


def test_claim_dish_success(client, mock_db_session):
    dish = _make_dish(status="processing")
    update_result = SimpleNamespace(rowcount=1)
    select_result = ScalarResult(first=dish)
    mock_db_session.execute = AsyncMock(side_effect=[update_result, select_result])

    response = client.post("/api/v1/dishes/1/claim")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == dish.id


def test_update_dish_updates_order_when_terminal(client, mock_db_session):
    dish = _make_dish(status="processing")
    order = _make_order(status="processing")
    mock_db_session.execute = AsyncMock(
        side_effect=[ScalarResult(first=dish), ScalarResult(first=order)]
    )

    response = client.put("/api/v1/dishes/1", json={"processing_status": "complete"})
    assert response.status_code == 200
    assert order.processing_status == "complete"
    assert order.is_active is False
