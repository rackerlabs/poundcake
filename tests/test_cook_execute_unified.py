from __future__ import annotations

from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from api.main import app
from api.services.execution_types import ExecutionResult


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
