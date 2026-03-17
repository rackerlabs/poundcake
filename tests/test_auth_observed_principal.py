from __future__ import annotations

import pytest
from fastapi import Response
from starlette.requests import Request

from api.api import auth as auth_api
from api.schemas.schemas import AuthLoginRequest
from api.services.auth_service import AccessDeniedError, AuthIdentity


class _FakeDB:
    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1


def _build_request() -> Request:
    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "POST",
        "scheme": "https",
        "path": "/api/v1/auth/login",
        "raw_path": b"/api/v1/auth/login",
        "query_string": b"",
        "headers": [],
        "client": ("127.0.0.1", 12345),
        "server": ("testserver", 443),
        "state": {},
    }
    request = Request(scope)
    request.state.req_id = "AUTH-LOGIN-TEST"
    return request


@pytest.mark.asyncio
async def test_password_login_records_observed_principal_before_returning_403(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_db = _FakeDB()
    observed: list[AuthIdentity] = []
    identity = AuthIdentity(
        provider="auth0",
        subject_id="auth0|test1",
        username="test1@example.com",
        display_name="Test1",
        groups=[],
        principal_type="user",
        is_superuser=False,
    )

    async def _fake_authenticate(provider: str, username: str, password: str) -> AuthIdentity:
        assert provider == "auth0"
        assert username == "test1"
        assert password == "secret"
        return identity

    async def _fake_build_login_context(db: _FakeDB, auth_identity: AuthIdentity) -> None:
        assert db is fake_db
        assert auth_identity is identity
        raise AccessDeniedError("No PoundCake role binding matches this user")

    async def _fake_upsert_principal(db: _FakeDB, auth_identity: AuthIdentity) -> object:
        assert db is fake_db
        observed.append(auth_identity)
        return object()

    monkeypatch.setattr(auth_api, "authenticate_password_provider", _fake_authenticate)
    monkeypatch.setattr(auth_api, "build_login_context", _fake_build_login_context)
    monkeypatch.setattr(auth_api, "upsert_principal", _fake_upsert_principal)

    with pytest.raises(auth_api.HTTPException) as exc_info:
        await auth_api.login(
            _build_request(),
            AuthLoginRequest(provider="auth0", username="test1", password="secret"),
            Response(),
            fake_db,
        )

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "No PoundCake role binding matches this user"
    assert observed == [identity]
    assert fake_db.rollbacks == 1
    assert fake_db.commits == 1
