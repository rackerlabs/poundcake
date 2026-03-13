from __future__ import annotations

from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from api.main import app


class _BeginContext:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None


def _valid_webhook_payload() -> dict:
    return {
        "status": "firing",
        "alerts": [
            {
                "status": "firing",
                "fingerprint": "fp-1",
                "startsAt": "2026-03-13T12:00:00Z",
                "labels": {
                    "alertname": "DiskFull",
                    "group_name": "filesystem-response",
                    "severity": "warning",
                    "instance": "host1",
                },
                "annotations": {
                    "summary": "Filesystem almost full",
                    "description": "Usage exceeded the alert threshold.",
                    "runbook_url": "https://docs.example.com/runbooks/filesystem",
                },
                "generatorURL": "https://prometheus.example/graph?g0.expr=node_filesystem",
            }
        ],
    }


def test_webhook_accepts_required_contract_fields() -> None:
    with patch("api.core.database.SessionLocal") as mock_session:
        db = AsyncMock()
        db.begin = lambda: _BeginContext()
        mock_session.return_value.__aenter__ = AsyncMock(return_value=db)
        mock_session.return_value.__aexit__ = AsyncMock(return_value=None)

        with patch(
            "api.api.webhook.pre_heat",
            new=AsyncMock(return_value={"status": "created", "order_id": 12, "results": []}),
        ) as pre_heat:
            client = TestClient(app)
            response = client.post("/api/v1/webhook", json=_valid_webhook_payload())

    assert response.status_code == 202
    assert response.json()["status"] == "created"
    pre_heat.assert_awaited_once()


def test_webhook_rejects_missing_required_annotation_fields() -> None:
    payload = _valid_webhook_payload()
    payload["alerts"][0]["annotations"].pop("description")

    with patch("api.core.database.SessionLocal") as mock_session:
        db = AsyncMock()
        mock_session.return_value.__aenter__ = AsyncMock(return_value=db)
        mock_session.return_value.__aexit__ = AsyncMock(return_value=None)
        client = TestClient(app)
        response = client.post("/api/v1/webhook", json=payload)

    assert response.status_code == 422
    assert "annotations missing required fields: description" in response.text
