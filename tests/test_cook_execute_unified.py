from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from api.main import app
from api.models.models import Order
from api.services.execution_types import ExecutionResult


class ScalarResult:
    def __init__(self, first=None):
        self._first = first

    def scalars(self):
        return self

    def first(self):
        return self._first


def test_cook_execute_returns_canonical_envelope_for_stackstorm():
    client = TestClient(app)
    with patch(
        "api.services.execution_orchestrator.ExecutionOrchestrator.execute",
        new=AsyncMock(
            return_value=ExecutionResult(
                engine="stackstorm",
                status="running",
                execution_ref="st2-123",
                raw={"id": "st2-123"},
                attempts=1,
            )
        ),
    ):
        response = client.post(
            "/api/v1/cook/execute",
            json={
                "execution_engine": "stackstorm",
                "execution_target": "poundcake.test",
                "execution_parameters": {},
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["engine"] == "stackstorm"
    assert body["status"] == "running"
    assert body["execution_ref"] == "st2-123"


def test_cook_execute_returns_canonical_envelope_for_bakery():
    client = TestClient(app)
    with patch(
        "api.services.execution_orchestrator.ExecutionOrchestrator.execute",
        new=AsyncMock(
            return_value=ExecutionResult(
                engine="bakery",
                status="succeeded",
                execution_ref="op-1",
                raw={"status": "succeeded"},
                attempts=1,
            )
        ),
    ):
        response = client.post(
            "/api/v1/cook/execute",
            json={
                "execution_engine": "bakery",
                "execution_target": "core",
                "execution_payload": {"title": "t", "description": "d"},
                "execution_parameters": {"operation": "ticket_create"},
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["engine"] == "bakery"
    assert body["status"] == "succeeded"
    assert body["execution_ref"] == "op-1"


def test_cook_execute_skips_bakery_call_for_suppressed_order():
    client = TestClient(app)
    now = datetime.now(timezone.utc)
    order = Order(
        id=42,
        req_id="REQ-42",
        fingerprint="fp-42",
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
    mock_db = SimpleNamespace(execute=AsyncMock(return_value=ScalarResult(first=order)))
    suppression = SimpleNamespace(id=5, name="upgrade in progress")
    orchestrator_execute = AsyncMock()

    with (
        patch("api.core.database.SessionLocal") as mock_session,
        patch(
            "api.api.cook.get_settings",
            return_value=SimpleNamespace(suppressions_enabled=True),
        ),
        patch(
            "api.api.cook.find_first_matching_suppression",
            new=AsyncMock(return_value=suppression),
        ),
        patch(
            "api.services.execution_orchestrator.ExecutionOrchestrator.execute",
            new=orchestrator_execute,
        ),
    ):
        mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session.return_value.__aexit__ = AsyncMock(return_value=None)
        response = client.post(
            "/api/v1/cook/execute",
            json={
                "execution_engine": "bakery",
                "execution_target": "core",
                "execution_payload": {"title": "t", "description": "d"},
                "execution_parameters": {"operation": "ticket_create"},
                "context": {"order_id": order.id},
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["engine"] == "bakery"
    assert body["status"] == "succeeded"
    assert body["raw"]["skipped"] is True
    assert body["raw"]["suppression_id"] == suppression.id
    orchestrator_execute.assert_not_awaited()


def test_cook_execute_rejects_invalid_engine_payload():
    client = TestClient(app)
    response = client.post(
        "/api/v1/cook/execute",
        json={
            "execution_engine": "native",
            "execution_target": "noop",
            "execution_parameters": {},
        },
    )
    assert response.status_code == 422


def test_cook_execute_rejects_non_object_execution_parameters():
    client = TestClient(app)
    response = client.post(
        "/api/v1/cook/execute",
        json={
            "execution_engine": "stackstorm",
            "execution_target": "poundcake.test",
            "execution_parameters": ["bad"],
        },
    )
    assert response.status_code == 422


def test_cook_execute_validation_error_returns_400():
    client = TestClient(app)
    response = client.post(
        "/api/v1/cook/execute",
        json={
            "execution_engine": "bakery",
            "execution_target": "not-a-route",
            "execution_payload": {"comment": "ok"},
            "execution_parameters": {"operation": "ticket_comment"},
        },
    )
    assert response.status_code == 400
    assert "execution_target" in response.json()["detail"]
