from __future__ import annotations

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
