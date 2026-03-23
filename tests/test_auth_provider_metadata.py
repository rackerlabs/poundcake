from __future__ import annotations

import asyncio
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from api.api import auth as auth_api
from api.core.config import get_settings
from api.main import app
from api.services.auth_service import DeviceAuthorizationStart
from api.services.auth_service import (
    auth0_browser_login_enabled,
    auth0_device_login_enabled,
    azure_ad_browser_login_enabled,
    azure_ad_device_login_enabled,
    get_enabled_provider_metadata,
)


@pytest.fixture(autouse=True)
def clear_settings_cache() -> None:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _provider(metadata: list[dict[str, object]], name: str) -> dict[str, object]:
    return next(item for item in metadata if item["name"] == name)


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
    auth0 = _provider(metadata, "auth0")

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
    auth0 = _provider(metadata, "auth0")

    assert auth0["browser_login"] is True
    assert auth0["device_login"] is True
    assert auth0["cli_login_mode"] == "device"
    assert auth0_browser_login_enabled() is True
    assert auth0_device_login_enabled() is True


def test_azure_ad_provider_metadata_reflects_split_ui_and_cli_clients(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("POUNDCAKE_AUTH_ENABLED", "true")
    monkeypatch.setenv("POUNDCAKE_AUTH_AZURE_AD_ENABLED", "true")
    monkeypatch.setenv("POUNDCAKE_AUTH_AZURE_AD_TENANT", "11111111-1111-1111-1111-111111111111")
    monkeypatch.setenv("POUNDCAKE_AUTH_AZURE_AD_UI_ENABLED", "true")
    monkeypatch.setenv("POUNDCAKE_AUTH_AZURE_AD_UI_CLIENT_ID", "azure-web-client")
    monkeypatch.setenv("POUNDCAKE_AUTH_AZURE_AD_CLI_ENABLED", "true")
    monkeypatch.setenv("POUNDCAKE_AUTH_AZURE_AD_CLI_CLIENT_ID", "azure-native-client")
    monkeypatch.setattr("api.services.auth_service.get_local_superuser_credentials", lambda: None)

    metadata = get_enabled_provider_metadata()
    azure_ad = _provider(metadata, "azure_ad")

    assert azure_ad["browser_login"] is True
    assert azure_ad["device_login"] is True
    assert azure_ad["cli_login_mode"] == "device"
    assert azure_ad_browser_login_enabled() is True
    assert azure_ad_device_login_enabled() is True


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


def test_oidc_login_requires_provider_when_multiple_browser_providers_are_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("POUNDCAKE_AUTH_ENABLED", "true")
    monkeypatch.setenv("POUNDCAKE_AUTH_AUTH0_ENABLED", "true")
    monkeypatch.setenv("POUNDCAKE_AUTH_AUTH0_DOMAIN", "tenant.example.auth0.com")
    monkeypatch.setenv("POUNDCAKE_AUTH_AUTH0_UI_ENABLED", "true")
    monkeypatch.setenv("POUNDCAKE_AUTH_AUTH0_UI_CLIENT_ID", "web-client")
    monkeypatch.setenv("POUNDCAKE_AUTH_AZURE_AD_ENABLED", "true")
    monkeypatch.setenv("POUNDCAKE_AUTH_AZURE_AD_TENANT", "11111111-1111-1111-1111-111111111111")
    monkeypatch.setenv("POUNDCAKE_AUTH_AZURE_AD_UI_ENABLED", "true")
    monkeypatch.setenv("POUNDCAKE_AUTH_AZURE_AD_UI_CLIENT_ID", "azure-web-client")

    client = TestClient(app)
    response = client.get("/api/v1/auth/oidc/login")

    assert response.status_code == 400
    assert (
        response.json()["detail"]
        == "provider is required when multiple browser login providers are enabled"
    )


def test_oidc_login_routes_to_explicit_azure_ad_provider_and_stores_nonce(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("POUNDCAKE_AUTH_ENABLED", "true")
    monkeypatch.setenv("POUNDCAKE_AUTH_AZURE_AD_ENABLED", "true")
    monkeypatch.setenv("POUNDCAKE_AUTH_AZURE_AD_TENANT", "11111111-1111-1111-1111-111111111111")
    monkeypatch.setenv("POUNDCAKE_AUTH_AZURE_AD_UI_ENABLED", "true")
    monkeypatch.setenv("POUNDCAKE_AUTH_AZURE_AD_UI_CLIENT_ID", "azure-web-client")
    monkeypatch.setenv("POUNDCAKE_REDIS_ENABLED", "false")

    async def _fake_authorize_url(
        provider: str,
        *,
        state: str,
        redirect_uri: str,
        nonce: str | None = None,
    ) -> str:
        assert provider == "azure_ad"
        assert redirect_uri.endswith("/api/v1/auth/oidc/callback")
        return f"https://login.example/{provider}?state={state}&nonce={nonce or ''}"

    monkeypatch.setattr("api.api.auth.get_oidc_authorize_url", _fake_authorize_url)

    client = TestClient(app)
    response = client.get(
        "/api/v1/auth/oidc/login",
        params={"provider": "azure_ad"},
        follow_redirects=False,
    )

    assert response.status_code == 307
    location = response.headers["location"]
    parsed = urlparse(location)
    params = parse_qs(parsed.query)
    state = params["state"][0]
    stored = asyncio.run(auth_api.get_session_store().get_value("oidc_state", state))

    assert parsed.path.endswith("/azure_ad")
    assert params["nonce"][0]
    assert stored == {
        "next": "/overview",
        "provider": "azure_ad",
        "nonce": params["nonce"][0],
    }


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


def test_device_start_requires_provider_when_multiple_device_providers_are_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("POUNDCAKE_AUTH_ENABLED", "true")
    monkeypatch.setenv("POUNDCAKE_AUTH_AUTH0_ENABLED", "true")
    monkeypatch.setenv("POUNDCAKE_AUTH_AUTH0_DOMAIN", "tenant.example.auth0.com")
    monkeypatch.setenv("POUNDCAKE_AUTH_AUTH0_CLI_ENABLED", "true")
    monkeypatch.setenv("POUNDCAKE_AUTH_AUTH0_CLI_CLIENT_ID", "native-client")
    monkeypatch.setenv("POUNDCAKE_AUTH_AZURE_AD_ENABLED", "true")
    monkeypatch.setenv("POUNDCAKE_AUTH_AZURE_AD_TENANT", "11111111-1111-1111-1111-111111111111")
    monkeypatch.setenv("POUNDCAKE_AUTH_AZURE_AD_CLI_ENABLED", "true")
    monkeypatch.setenv("POUNDCAKE_AUTH_AZURE_AD_CLI_CLIENT_ID", "azure-native-client")

    client = TestClient(app)
    response = client.post("/api/v1/auth/device/start")

    assert response.status_code == 400
    assert (
        response.json()["detail"]
        == "provider is required when multiple CLI device login providers are enabled"
    )


def test_device_start_accepts_explicit_azure_ad_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("POUNDCAKE_AUTH_ENABLED", "true")
    monkeypatch.setenv("POUNDCAKE_AUTH_AZURE_AD_ENABLED", "true")
    monkeypatch.setenv("POUNDCAKE_AUTH_AZURE_AD_TENANT", "11111111-1111-1111-1111-111111111111")
    monkeypatch.setenv("POUNDCAKE_AUTH_AZURE_AD_CLI_ENABLED", "true")
    monkeypatch.setenv("POUNDCAKE_AUTH_AZURE_AD_CLI_CLIENT_ID", "azure-native-client")

    async def _fake_start(provider: str) -> DeviceAuthorizationStart:
        assert provider == "azure_ad"
        return DeviceAuthorizationStart(
            provider="azure_ad",
            device_code="device-123",
            user_code="ABCD-EFGH",
            verification_uri="https://microsoft.example/device",
            verification_uri_complete="https://microsoft.example/device?code=ABCD-EFGH",
            expires_in=600,
            interval=5,
        )

    monkeypatch.setattr("api.api.auth.start_device_authorization", _fake_start)

    client = TestClient(app)
    response = client.post("/api/v1/auth/device/start", json={"provider": "azure_ad"})

    assert response.status_code == 200
    assert response.json()["provider"] == "azure_ad"
