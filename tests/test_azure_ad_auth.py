from __future__ import annotations

import pytest

from api.core.config import get_settings
from api.services.auth_service import (
    InvalidCredentialsError,
    _azure_ad_identity_from_claims,
    _decode_azure_ad_id_token,
)


@pytest.fixture(autouse=True)
def clear_settings_cache() -> None:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _configure_azure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("POUNDCAKE_AUTH_ENABLED", "true")
    monkeypatch.setenv("POUNDCAKE_AUTH_AZURE_AD_ENABLED", "true")
    monkeypatch.setenv("POUNDCAKE_AUTH_AZURE_AD_TENANT", "11111111-1111-1111-1111-111111111111")
    monkeypatch.setenv("POUNDCAKE_AUTH_AZURE_AD_UI_ENABLED", "true")
    monkeypatch.setenv("POUNDCAKE_AUTH_AZURE_AD_UI_CLIENT_ID", "azure-web-client")
    monkeypatch.setenv("POUNDCAKE_AUTH_AZURE_AD_CLI_ENABLED", "true")
    monkeypatch.setenv("POUNDCAKE_AUTH_AZURE_AD_CLI_CLIENT_ID", "azure-native-client")


@pytest.mark.asyncio
async def test_decode_azure_ad_id_token_passes_expected_issuer_and_audience(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_azure(monkeypatch)
    seen: dict[str, object] = {}

    async def _fake_discovery() -> dict[str, str]:
        return {
            "issuer": "https://login.microsoftonline.com/11111111-1111-1111-1111-111111111111/v2.0",
            "authorization_endpoint": "https://login.microsoftonline.com/example/oauth2/v2.0/authorize",
            "token_endpoint": "https://login.microsoftonline.com/example/oauth2/v2.0/token",
            "jwks_uri": "https://login.microsoftonline.com/example/discovery/v2.0/keys",
            "device_authorization_endpoint": "https://login.microsoftonline.com/example/oauth2/v2.0/devicecode",
        }

    async def _fake_jwks() -> dict[str, object]:
        return {"keys": [{"kid": "test-key"}]}

    def _fake_decode(
        token: str,
        key: object,
        algorithms: list[str] | None = None,
        options: dict[str, object] | None = None,
        audience: str | None = None,
        issuer: str | None = None,
        subject: str | None = None,
        access_token: str | None = None,
    ) -> dict[str, object]:
        seen["token"] = token
        seen["key"] = key
        seen["algorithms"] = algorithms
        seen["options"] = options
        seen["audience"] = audience
        seen["issuer"] = issuer
        seen["subject"] = subject
        seen["access_token"] = access_token
        return {
            "sub": "azure-user-1",
            "preferred_username": "alice@example.com",
            "name": "Alice Example",
            "groups": ["monitoring-operators"],
            "nonce": "nonce-123",
            "tid": "11111111-1111-1111-1111-111111111111",
        }

    monkeypatch.setattr("api.services.auth_service._azure_ad_discovery_document", _fake_discovery)
    monkeypatch.setattr("api.services.auth_service._azure_ad_jwks", _fake_jwks)
    monkeypatch.setattr("jose.jwt.decode", _fake_decode)

    identity = await _decode_azure_ad_id_token(
        "id-token-123",
        client_id="azure-web-client",
        expected_nonce="nonce-123",
    )

    assert seen["token"] == "id-token-123"
    assert seen["audience"] == "azure-web-client"
    assert (
        seen["issuer"]
        == "https://login.microsoftonline.com/11111111-1111-1111-1111-111111111111/v2.0"
    )
    assert seen["algorithms"] == ["RS256"]
    assert seen["options"] == {"verify_at_hash": False}
    assert identity.provider == "azure_ad"
    assert identity.username == "alice@example.com"
    assert identity.groups == ["monitoring-operators"]


def test_azure_ad_identity_from_claims_rejects_nonce_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_azure(monkeypatch)

    with pytest.raises(InvalidCredentialsError, match="nonce"):
        _azure_ad_identity_from_claims(
            {
                "sub": "azure-user-1",
                "preferred_username": "alice@example.com",
                "name": "Alice Example",
                "nonce": "unexpected",
                "tid": "11111111-1111-1111-1111-111111111111",
            },
            expected_nonce="nonce-123",
        )


def test_azure_ad_identity_from_claims_rejects_tenant_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_azure(monkeypatch)

    with pytest.raises(InvalidCredentialsError, match="tenant"):
        _azure_ad_identity_from_claims(
            {
                "sub": "azure-user-1",
                "preferred_username": "alice@example.com",
                "name": "Alice Example",
                "tid": "22222222-2222-2222-2222-222222222222",
            }
        )


def test_azure_ad_identity_from_claims_treats_group_overage_as_no_groups(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_azure(monkeypatch)

    identity = _azure_ad_identity_from_claims(
        {
            "sub": "azure-user-1",
            "preferred_username": "alice@example.com",
            "name": "Alice Example",
            "tid": "11111111-1111-1111-1111-111111111111",
            "_claim_names": {"groups": "src1"},
            "_claim_sources": {"src1": {"endpoint": "https://graph.example/groups"}},
        }
    )

    assert identity.groups == []
