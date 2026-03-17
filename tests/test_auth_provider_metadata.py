from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api.core.config import get_settings
from api.main import app
from api.services.auth_service import (
    auth0_browser_login_enabled,
    auth0_device_login_enabled,
    get_enabled_provider_metadata,
)


@pytest.fixture(autouse=True)
def clear_settings_cache() -> None:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _auth0_provider(metadata: list[dict[str, object]]) -> dict[str, object]:
    return next(item for item in metadata if item["name"] == "auth0")


def test_auth0_provider_metadata_reflects_browser_only_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("POUNDCAKE_AUTH_ENABLED", "true")
    monkeypatch.setenv("POUNDCAKE_AUTH_AUTH0_ENABLED", "true")
    monkeypatch.setenv("POUNDCAKE_AUTH_AUTH0_DOMAIN", "tenant.example.auth0.com")
    monkeypatch.setenv("POUNDCAKE_AUTH_AUTH0_UI_ENABLED", "true")
    monkeypatch.setenv("POUNDCAKE_AUTH_AUTH0_UI_CLIENT_ID", "web-client")
    monkeypatch.setenv("POUNDCAKE_AUTH_AUTH0_CLI_ENABLED", "false")
    monkeypatch.delenv("POUNDCAKE_AUTH_AUTH0_CLI_CLIENT_ID", raising=False)
    monkeypatch.setattr("api.services.auth_service.get_local_superuser_credentials", lambda: None)

    metadata = get_enabled_provider_metadata()
    auth0 = _auth0_provider(metadata)

    assert auth0["browser_login"] is True
    assert auth0["device_login"] is False
    assert auth0["cli_login_mode"] == "unavailable"
    assert auth0_browser_login_enabled() is True
    assert auth0_device_login_enabled() is False


def test_auth0_provider_metadata_reflects_split_ui_and_cli_clients(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("POUNDCAKE_AUTH_ENABLED", "true")
    monkeypatch.setenv("POUNDCAKE_AUTH_AUTH0_ENABLED", "true")
    monkeypatch.setenv("POUNDCAKE_AUTH_AUTH0_DOMAIN", "tenant.example.auth0.com")
    monkeypatch.setenv("POUNDCAKE_AUTH_AUTH0_UI_ENABLED", "true")
    monkeypatch.setenv("POUNDCAKE_AUTH_AUTH0_UI_CLIENT_ID", "web-client")
    monkeypatch.setenv("POUNDCAKE_AUTH_AUTH0_CLI_ENABLED", "true")
    monkeypatch.setenv("POUNDCAKE_AUTH_AUTH0_CLI_CLIENT_ID", "native-client")
    monkeypatch.setattr("api.services.auth_service.get_local_superuser_credentials", lambda: None)

    metadata = get_enabled_provider_metadata()
    auth0 = _auth0_provider(metadata)

    assert auth0["browser_login"] is True
    assert auth0["device_login"] is True
    assert auth0["cli_login_mode"] == "device"
    assert auth0_browser_login_enabled() is True
    assert auth0_device_login_enabled() is True


def test_oidc_login_returns_404_when_auth0_browser_login_is_not_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("POUNDCAKE_AUTH_ENABLED", "true")
    monkeypatch.setenv("POUNDCAKE_AUTH_AUTH0_ENABLED", "true")
    monkeypatch.setenv("POUNDCAKE_AUTH_AUTH0_DOMAIN", "tenant.example.auth0.com")
    monkeypatch.setenv("POUNDCAKE_AUTH_AUTH0_UI_ENABLED", "false")
    monkeypatch.setenv("POUNDCAKE_AUTH_AUTH0_CLI_ENABLED", "true")
    monkeypatch.setenv("POUNDCAKE_AUTH_AUTH0_CLI_CLIENT_ID", "native-client")

    client = TestClient(app)
    response = client.get("/api/v1/auth/oidc/login")

    assert response.status_code == 404
    assert response.json()["detail"] == "Auth0 browser login is not enabled"


def test_device_start_returns_404_when_auth0_cli_login_is_not_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("POUNDCAKE_AUTH_ENABLED", "true")
    monkeypatch.setenv("POUNDCAKE_AUTH_AUTH0_ENABLED", "true")
    monkeypatch.setenv("POUNDCAKE_AUTH_AUTH0_DOMAIN", "tenant.example.auth0.com")
    monkeypatch.setenv("POUNDCAKE_AUTH_AUTH0_UI_ENABLED", "true")
    monkeypatch.setenv("POUNDCAKE_AUTH_AUTH0_UI_CLIENT_ID", "web-client")
    monkeypatch.setenv("POUNDCAKE_AUTH_AUTH0_CLI_ENABLED", "false")

    client = TestClient(app)
    response = client.post("/api/v1/auth/device/start")

    assert response.status_code == 404
    assert response.json()["detail"] == "Auth0 CLI device login is not enabled"
