from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from api.main import app


def test_settings_reports_global_communications_configuration_flag():
    with patch("api.core.database.SessionLocal") as mock_session:
        db = AsyncMock()
        mock_session.return_value.__aenter__ = AsyncMock(return_value=db)
        mock_session.return_value.__aexit__ = AsyncMock(return_value=None)
        client = TestClient(app)

        with patch(
            "api.api.settings.global_policy_configured",
            new=AsyncMock(return_value=True),
        ):
            response = client.get("/api/v1/settings")

    assert response.status_code == 200
    assert response.json()["global_communications_configured"] is True


def test_settings_reports_git_repo_paths_when_enabled():
    fake_settings = SimpleNamespace(
        auth_enabled=True,
        auth_rbac_enabled=True,
        prometheus_use_crds=True,
        prometheus_crd_namespace="prometheus",
        prometheus_url="http://prometheus.example:9090",
        git_enabled=True,
        git_provider="github",
        git_repo_url="https://github.com/example/config.git",
        git_branch="config-main",
        git_rules_path="prometheus/rules",
        git_workflows_path="poundcake/workflows",
        git_actions_path="poundcake/actions",
        app_version="2.0.142",
    )

    with patch("api.core.database.SessionLocal") as mock_session:
        db = AsyncMock()
        mock_session.return_value.__aenter__ = AsyncMock(return_value=db)
        mock_session.return_value.__aexit__ = AsyncMock(return_value=None)
        client = TestClient(app)

        with (
            patch("api.api.settings.get_settings", return_value=fake_settings),
            patch(
                "api.api.settings.global_policy_configured",
                new=AsyncMock(return_value=False),
            ),
            patch("api.api.settings.get_enabled_provider_metadata", return_value=[]),
        ):
            response = client.get("/api/v1/settings")

    assert response.status_code == 200
    payload = response.json()
    assert payload["git_enabled"] is True
    assert payload["git_provider"] == "github"
    assert payload["git_repo_url"] == "https://github.com/example/config.git"
    assert payload["git_branch"] == "config-main"
    assert payload["git_rules_path"] == "prometheus/rules"
    assert payload["git_workflows_path"] == "poundcake/workflows"
    assert payload["git_actions_path"] == "poundcake/actions"
