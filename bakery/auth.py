#!/usr/bin/env python3
"""HMAC authentication helpers for Bakery service-to-service API calls."""

from __future__ import annotations

import secrets
import time
from typing import Optional

from fastapi import Header, HTTPException, Request, status

from bakery.config import settings
from shared.hmac import build_hmac_signing_payload, hmac_sha256_hex


def _resolve_key(key_id: str) -> Optional[str]:
    if key_id == settings.bakery_hmac_active_key_id and settings.bakery_hmac_active_key:
        return settings.bakery_hmac_active_key
    if key_id == settings.bakery_hmac_next_key_id and settings.bakery_hmac_next_key:
        return settings.bakery_hmac_next_key
    return None


def _validate_timestamp(ts_raw: str) -> None:
    try:
        ts = int(ts_raw)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid X-Timestamp header",
        ) from exc

    now = int(time.time())
    if abs(now - ts) > settings.bakery_hmac_timestamp_skew_sec:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Request timestamp outside allowed skew window",
        )


async def require_hmac_auth(
    request: Request,
    authorization: str | None = Header(default=None, alias="Authorization"),
    x_timestamp: str | None = Header(default=None, alias="X-Timestamp"),
) -> str:
    """
    Authenticate Bakery API requests using:
      Authorization: HMAC <key_id>:<hex_signature>
      X-Timestamp: <unix_epoch_seconds>
    """
    # Health endpoint remains open.
    if request.url.path.endswith("/health"):
        return "__health__"

    if not settings.bakery_auth_enabled:
        return "__auth_disabled__"
    if settings.bakery_auth_mode.lower() != "hmac":
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unsupported auth mode",
        )

    if not authorization or not authorization.startswith("HMAC "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid Authorization header",
        )

    if not x_timestamp:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing X-Timestamp header",
        )

    _validate_timestamp(x_timestamp)

    token = authorization[len("HMAC ") :].strip()
    if ":" not in token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid HMAC authorization format",
        )
    key_id, signature = token.split(":", 1)
    key_id = key_id.strip()
    signature = signature.strip().lower()
    if not key_id or not signature:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid HMAC authorization format",
        )

    shared_secret = _resolve_key(key_id)
    if not shared_secret:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unknown key id",
        )

    body = await request.body()
    payload = build_hmac_signing_payload(
        timestamp=x_timestamp,
        method=request.method,
        path=request.url.path,
        body=body,
    )
    expected = hmac_sha256_hex(shared_secret, payload)
    if not secrets.compare_digest(expected, signature):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid request signature",
        )

    return key_id
