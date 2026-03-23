from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from api.main import app
from api.services.execution_types import ExecutionResult


@pytest.fixture
def client():
    with patch("api.core.database.SessionLocal") as mock_session:
        db = AsyncMock()
        mock_session.return_value.__aenter__ = AsyncMock(return_value=db)
        mock_session.return_value.__aexit__ = AsyncMock(return_value=None)
        yield TestClient(app)


def test_cook_execute_returns_canonical_envelope_for_stackstorm(client):
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


def test_cook_execute_returns_canonical_envelope_for_bakery(client):
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


def test_cook_execute_resolves_template_bakery_payload_before_execution(client):
    captured: dict[str, object] = {}

    async def _execute(ctx):
        captured["payload"] = ctx.execution_payload
        return ExecutionResult(
            engine="bakery",
            status="succeeded",
            execution_ref="op-2",
            raw={"status": "succeeded"},
            attempts=1,
        )

    with patch(
        "api.services.execution_orchestrator.ExecutionOrchestrator.execute",
        new=AsyncMock(side_effect=_execute),
    ):
        response = client.post(
            "/api/v1/cook/execute",
            json={
                "execution_engine": "bakery",
                "execution_target": "core",
                "execution_payload": {
                    "template": {
                        "comment": "template comment",
                        "context": {"labels": {"team": "storage"}},
                    },
                    "context": {"labels": {"service": "disk"}},
                },
                "execution_parameters": {"operation": "ticket_comment"},
            },
        )

    assert response.status_code == 200
    resolved = captured["payload"]
    assert isinstance(resolved, dict)
    assert resolved["comment"] == "template comment"
    assert "template" not in resolved
    assert resolved["context"]["provider_type"] == "core"
    assert resolved["context"]["labels"] == {"team": "storage", "service": "disk"}


def test_cook_execute_rejects_invalid_engine_payload(client):
    response = client.post(
        "/api/v1/cook/execute",
        json={
            "execution_engine": "native",
            "execution_target": "noop",
            "execution_parameters": {},
        },
    )
    assert response.status_code == 422


def test_cook_execute_rejects_non_object_execution_parameters(client):
    response = client.post(
        "/api/v1/cook/execute",
        json={
            "execution_engine": "stackstorm",
            "execution_target": "poundcake.test",
            "execution_parameters": ["bad"],
        },
    )
    assert response.status_code == 422


def test_cook_execute_validation_error_returns_400(client):
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
