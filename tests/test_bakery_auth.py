"""Regression tests for Bakery HMAC auth."""

from __future__ import annotations

import time

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from bakery.auth import require_hmac_auth
from bakery.config import settings
from shared.hmac import build_hmac_signing_payload, hmac_sha256_hex


def _signed_headers(
    *,
    key_id: str,
    key: str,
    method: str,
    path: str,
    body: bytes,
    timestamp: str | None = None,
) -> dict[str, str]:
    ts = timestamp or str(int(time.time()))
    payload = build_hmac_signing_payload(ts, method, path, body)
    signature = hmac_sha256_hex(key, payload)
    return {
        "Authorization": f"HMAC {key_id}:{signature}",
        "X-Timestamp": ts,
        "Content-Type": "application/json",
    }


def _app() -> FastAPI:
    app = FastAPI()

    @app.post("/api/v1/tickets", dependencies=[Depends(require_hmac_auth)])
    async def create_ticket() -> dict[str, str]:
        return {"status": "ok"}

    return app


def test_require_hmac_auth_accepts_valid_signature(monkeypatch) -> None:
    monkeypatch.setattr(settings, "bakery_auth_enabled", True)
    monkeypatch.setattr(settings, "bakery_auth_mode", "hmac")
    monkeypatch.setattr(settings, "bakery_hmac_active_key_id", "active-id")
    monkeypatch.setattr(settings, "bakery_hmac_active_key", "active-secret")
    monkeypatch.setattr(settings, "bakery_hmac_next_key_id", "")
    monkeypatch.setattr(settings, "bakery_hmac_next_key", "")
    monkeypatch.setattr(settings, "bakery_hmac_timestamp_skew_sec", 300)

    client = TestClient(_app())
    body = b'{"title":"test"}'
    headers = _signed_headers(
        key_id="active-id",
        key="active-secret",
        method="POST",
        path="/api/v1/tickets",
        body=body,
    )
    response = client.post("/api/v1/tickets", content=body, headers=headers)
    assert response.status_code == 200


def test_require_hmac_auth_rejects_invalid_signature(monkeypatch) -> None:
    monkeypatch.setattr(settings, "bakery_auth_enabled", True)
    monkeypatch.setattr(settings, "bakery_auth_mode", "hmac")
    monkeypatch.setattr(settings, "bakery_hmac_active_key_id", "active-id")
    monkeypatch.setattr(settings, "bakery_hmac_active_key", "active-secret")
    monkeypatch.setattr(settings, "bakery_hmac_timestamp_skew_sec", 300)

    client = TestClient(_app())
    body = b'{"title":"test"}'
    headers = _signed_headers(
        key_id="active-id",
        key="active-secret",
        method="POST",
        path="/api/v1/tickets",
        body=body,
    )
    headers["Authorization"] = headers["Authorization"][:-1] + "0"
    response = client.post("/api/v1/tickets", content=body, headers=headers)
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid request signature"


def test_require_hmac_auth_rejects_stale_timestamp(monkeypatch) -> None:
    monkeypatch.setattr(settings, "bakery_auth_enabled", True)
    monkeypatch.setattr(settings, "bakery_auth_mode", "hmac")
    monkeypatch.setattr(settings, "bakery_hmac_active_key_id", "active-id")
    monkeypatch.setattr(settings, "bakery_hmac_active_key", "active-secret")
    monkeypatch.setattr(settings, "bakery_hmac_timestamp_skew_sec", 1)

    client = TestClient(_app())
    body = b'{"title":"test"}'
    stale = str(int(time.time()) - 30)
    headers = _signed_headers(
        key_id="active-id",
        key="active-secret",
        method="POST",
        path="/api/v1/tickets",
        body=body,
        timestamp=stale,
    )
    response = client.post("/api/v1/tickets", content=body, headers=headers)
    assert response.status_code == 401
    assert response.json()["detail"] == "Request timestamp outside allowed skew window"


def test_require_hmac_auth_rejects_unknown_key(monkeypatch) -> None:
    monkeypatch.setattr(settings, "bakery_auth_enabled", True)
    monkeypatch.setattr(settings, "bakery_auth_mode", "hmac")
    monkeypatch.setattr(settings, "bakery_hmac_active_key_id", "active-id")
    monkeypatch.setattr(settings, "bakery_hmac_active_key", "active-secret")
    monkeypatch.setattr(settings, "bakery_hmac_next_key_id", "")
    monkeypatch.setattr(settings, "bakery_hmac_next_key", "")
    monkeypatch.setattr(settings, "bakery_hmac_timestamp_skew_sec", 300)

    client = TestClient(_app())
    body = b'{"title":"test"}'
    headers = _signed_headers(
        key_id="unknown-id",
        key="unknown-secret",
        method="POST",
        path="/api/v1/tickets",
        body=body,
    )
    response = client.post("/api/v1/tickets", content=body, headers=headers)
    assert response.status_code == 401
    assert response.json()["detail"] == "Unknown key id"
