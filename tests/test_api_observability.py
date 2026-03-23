"""Tests for observability and communication activity endpoints."""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from api.main import app
from api.models.models import (
    AlertSuppression,
    Dish,
    Order,
    OrderCommunication,
    Recipe,
    SuppressionSummary,
)


class ScalarResult:
    def __init__(self, all_=None):
        self._all = all_ or []

    def scalars(self):
        return self

    def all(self):
        return self._all

    def unique(self):
        return self


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def mock_db():
    with patch("api.core.database.SessionLocal") as mock_session:
        db = AsyncMock()
        mock_session.return_value.__aenter__ = AsyncMock(return_value=db)
        mock_session.return_value.__aexit__ = AsyncMock(return_value=None)
        yield db


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
        alert_group_name="NodeFilesystemAlmostOutOfSpace",
        severity="critical",
        instance="node-1",
        counter=2,
        bakery_ticket_id=None,
        bakery_operation_id=None,
        bakery_ticket_state=None,
        bakery_permanent_failure=False,
        bakery_last_error=None,
        labels={"alertname": "NodeFilesystemAlmostOutOfSpace"},
        annotations={"summary": "Disk filling up"},
        raw_data={},
        starts_at=now,
        ends_at=None,
        created_at=now,
        updated_at=now,
    )
    communication = OrderCommunication(
        id=17,
        order_id=order_id,
        execution_target="teams",
        destination_target="ops-alerts",
        bakery_ticket_id="teams-message-123",
        bakery_operation_id="op-teams-1",
        lifecycle_state="sent",
        remote_state="delivered",
        writable=True,
        reopenable=False,
        last_error=None,
        created_at=now,
        updated_at=now,
    )
    order.communications = [communication]
    return order


def _make_suppression() -> tuple[AlertSuppression, SuppressionSummary]:
    now = datetime.now(timezone.utc)
    suppression = AlertSuppression(
        id=5,
        name="Database maintenance",
        reason="Planned change window",
        scope="matchers",
        enabled=True,
        starts_at=now,
        ends_at=now,
        canceled_at=None,
        created_by="ui",
        summary_ticket_enabled=True,
        created_at=now,
        updated_at=now,
    )
    summary = SuppressionSummary(
        id=7,
        suppression_id=5,
        total_suppressed=9,
        total_cleared=3,
        total_still_firing=1,
        by_alertname_json={},
        by_severity_json={},
        still_firing_alerts_json={},
        first_seen_at=now,
        last_seen_at=now,
        summary_created_at=now,
        bakery_ticket_id="260312-02074",
        bakery_create_operation_id="summary-create-1",
        bakery_close_operation_id=None,
        summary_close_at=None,
        state="created",
        last_error=None,
        created_at=now,
        updated_at=now,
    )
    summary.suppression = suppression
    return suppression, summary


def _make_dish(order: Order) -> Dish:
    now = datetime.now(timezone.utc)
    recipe = Recipe(
        id=3,
        name="node-filesystem-workflow",
        description="Disk response",
        enabled=True,
        clear_timeout_sec=300,
        created_at=now,
        updated_at=now,
        deleted=False,
        deleted_at=None,
    )
    dish = Dish(
        id=13,
        req_id="REQ-1",
        order_id=order.id,
        recipe_id=recipe.id,
        run_phase="firing",
        processing_status="processing",
        expected_duration_sec=60,
        actual_duration_sec=None,
        execution_status="running",
        execution_ref="st2-abc123",
        started_at=now,
        completed_at=None,
        result=None,
        error_message=None,
        retry_attempt=0,
        created_at=now,
        updated_at=now,
    )
    dish.recipe = recipe
    dish.order = order
    return dish


def test_communications_activity_returns_incident_and_suppression_rows(client, mock_db):
    order = _make_order()
    _suppression, summary = _make_suppression()

    mock_db.execute = AsyncMock(
        side_effect=[
            ScalarResult(all_=[order]),
            ScalarResult(all_=[summary]),
        ]
    )

    response = client.get("/api/v1/communications/activity")

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    incident_row = next(item for item in data if item["reference_type"] == "incident")
    suppression_row = next(item for item in data if item["reference_type"] == "suppression")
    assert incident_row["channel"] == "teams"
    assert incident_row["provider_reference_id"] == "teams-message-123"
    assert suppression_row["ticket_id"] == "260312-02074"


def test_observability_activity_returns_clickable_typed_feed(client, mock_db):
    order = _make_order()
    _suppression, summary = _make_suppression()
    dish = _make_dish(order)

    mock_db.execute = AsyncMock(
        side_effect=[
            ScalarResult(all_=[order]),
            ScalarResult(all_=[dish]),
            ScalarResult(all_=[order]),
            ScalarResult(all_=[summary]),
            ScalarResult(all_=[summary.suppression]),
        ]
    )

    response = client.get("/api/v1/observability/activity")

    assert response.status_code == 200
    data = response.json()
    assert {item["type"] for item in data} == {
        "incident",
        "automation",
        "communication",
        "suppression",
    }
    incident_item = next(item for item in data if item["type"] == "incident")
    communication_item = next(
        item
        for item in data
        if item["type"] == "communication" and item["metadata"]["reference_type"] == "incident"
    )
    assert incident_item["link_hint"] == "/incidents/1"
    assert communication_item["link_hint"] == "/incidents/1?communication=17"


def test_observability_activity_accepts_naive_suppression_timestamps(client, mock_db):
    order = _make_order()
    _suppression, summary = _make_suppression()
    dish = _make_dish(order)
    summary.suppression.starts_at = (datetime.now(timezone.utc) - timedelta(minutes=1)).replace(
        tzinfo=None
    )
    summary.suppression.ends_at = (datetime.now(timezone.utc) + timedelta(minutes=1)).replace(
        tzinfo=None
    )
    summary.suppression.updated_at = summary.suppression.updated_at.replace(tzinfo=None)

    mock_db.execute = AsyncMock(
        side_effect=[
            ScalarResult(all_=[order]),
            ScalarResult(all_=[dish]),
            ScalarResult(all_=[order]),
            ScalarResult(all_=[summary]),
            ScalarResult(all_=[summary.suppression]),
        ]
    )

    response = client.get("/api/v1/observability/activity")

    assert response.status_code == 200
    suppression_item = next(item for item in response.json() if item["type"] == "suppression")
    assert suppression_item["status"] == "active"
    assert suppression_item["timestamp"].endswith("Z")
