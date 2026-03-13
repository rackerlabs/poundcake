from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from fastapi.testclient import TestClient

from api.main import app


class _BeginContext:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None


def _route(
    *,
    route_id: str,
    label: str,
    execution_target: str,
    destination_target: str,
    provider_config: dict | None = None,
    enabled: bool = True,
    position: int = 1,
):
    return SimpleNamespace(
        id=route_id,
        label=label,
        execution_target=execution_target,
        destination_target=destination_target,
        provider_config=provider_config or {},
        enabled=enabled,
        position=position,
    )


def test_get_communications_policy_returns_provider_neutral_routes():
    with patch("api.core.database.SessionLocal") as mock_session:
        db = AsyncMock()
        mock_session.return_value.__aenter__ = AsyncMock(return_value=db)
        mock_session.return_value.__aexit__ = AsyncMock(return_value=None)
        client = TestClient(app)

        routes = [
            _route(
                route_id="route-teams",
                label="Teams war room",
                execution_target="teams",
                destination_target="ops-alerts",
            )
        ]

        with patch(
            "api.api.communications_policy.get_global_policy_routes",
            new=AsyncMock(return_value=routes),
        ):
            response = client.get("/api/v1/communications/policy")

    assert response.status_code == 200
    body = response.json()
    assert body["configured"] is True
    assert body["routes"][0]["execution_target"] == "teams"
    assert body["routes"][0]["destination_target"] == "ops-alerts"
    assert "clear_after_escalation" in body["lifecycle_summary"]


def test_put_communications_policy_accepts_teams_only_policy_and_syncs_fallback():
    with patch("api.core.database.SessionLocal") as mock_session:
        db = AsyncMock()
        db.begin = Mock(return_value=_BeginContext())
        mock_session.return_value.__aenter__ = AsyncMock(return_value=db)
        mock_session.return_value.__aexit__ = AsyncMock(return_value=None)
        client = TestClient(app)

        synced_routes = [
            _route(
                route_id="route-teams",
                label="Teams war room",
                execution_target="teams",
                destination_target="ops-alerts",
            )
        ]

        with (
            patch(
                "api.api.communications_policy.sync_global_policy_routes",
                new=AsyncMock(return_value=synced_routes),
            ) as sync_global,
            patch(
                "api.api.communications_policy.sync_fallback_policy_recipe",
                new=AsyncMock(return_value=SimpleNamespace(id=22, name="fallback-recipe")),
            ) as sync_fallback,
        ):
            response = client.put(
                "/api/v1/communications/policy",
                json={
                    "routes": [
                        {
                            "label": "Teams war room",
                            "execution_target": "teams",
                            "destination_target": "ops-alerts",
                            "enabled": True,
                            "position": 1,
                        }
                    ]
                },
            )

    assert response.status_code == 200
    body = response.json()
    assert body["configured"] is True
    assert body["routes"][0]["label"] == "Teams war room"
    sync_global.assert_awaited_once()
    sync_fallback.assert_awaited_once()
    assert sync_fallback.await_args.kwargs["routes"] == synced_routes
