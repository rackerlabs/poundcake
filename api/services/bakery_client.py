"""Bakery client for PoundCake ticket operations."""

from __future__ import annotations

import asyncio
import hashlib
import time
import uuid
from typing import Any

from api.core.config import get_settings
from api.core.http_client import request_with_retry
from api.core.logging import get_logger
from api.core.metrics import record_bakery_request_failure
from shared.hmac import build_hmac_signing_payload, canonical_json_body, hmac_sha256_hex

logger = get_logger(__name__)

TERMINAL_OPERATION_STATUSES = {"succeeded", "dead_letter"}


def _canonical_body(payload: dict[str, Any] | None) -> str:
    return canonical_json_body(payload)


def _sign_request(method: str, path: str, body: str, ts: str) -> str:
    settings = get_settings()
    signing_payload = build_hmac_signing_payload(ts, method, path, body.encode("utf-8"))
    digest = hmac_sha256_hex(settings.bakery_hmac_key, signing_payload)
    return f"HMAC {settings.bakery_hmac_key_id}:{digest}"


def _build_headers(method: str, path: str, payload: dict[str, Any] | None) -> dict[str, str]:
    settings = get_settings()
    headers = {"Content-Type": "application/json"}
    if settings.bakery_auth_mode.lower() != "hmac":
        return headers
    body = _canonical_body(payload)
    ts = str(int(time.time()))
    headers["Authorization"] = _sign_request(method, path, body, ts)
    headers["X-Timestamp"] = ts
    return headers


def build_idempotency_key(req_id: str, action: str) -> str:
    seed = f"{req_id}:{action}:{uuid.uuid4()}"
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()


def _redact_key(key: str) -> str:
    if len(key) < 8:
        return "redacted"
    return f"{key[:4]}...{key[-4:]}"


async def _request(
    action: str,
    method: str,
    path: str,
    *,
    payload: dict[str, Any] | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    settings = get_settings()
    url = f"{settings.bakery_base_url.rstrip('/')}{path}"
    body = _canonical_body(payload)
    headers = _build_headers(method, path, payload)
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key

    try:
        response = await request_with_retry(
            method,
            url,
            headers=headers,
            content=body.encode("utf-8") if body else None,
            timeout=settings.bakery_request_timeout_seconds,
            retries=settings.bakery_max_retries,
        )
    except Exception as exc:  # noqa: BLE001
        record_bakery_request_failure(action, "transport_exception")
        logger.error(
            "Bakery request transport failure",
            extra={"action": action, "path": path, "error": str(exc)},
        )
        raise

    if response.status_code >= 400:
        reason = f"http_{response.status_code}"
        record_bakery_request_failure(action, reason)
        logger.error(
            "Bakery request failed",
            extra={
                "action": action,
                "path": path,
                "status_code": response.status_code,
                "idempotency_key": _redact_key(idempotency_key or ""),
                "response": response.text,
            },
        )
        response.raise_for_status()

    return response.json()


async def create_ticket(req_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    return await _request(
        "create",
        "POST",
        "/api/v1/tickets",
        payload=payload,
        idempotency_key=build_idempotency_key(req_id, "create"),
    )


async def close_ticket(req_id: str, ticket_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    return await _request(
        "close",
        "POST",
        f"/api/v1/tickets/{ticket_id}/close",
        payload=payload,
        idempotency_key=build_idempotency_key(req_id, "close"),
    )


async def update_ticket(req_id: str, ticket_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    return await _request(
        "update",
        "PATCH",
        f"/api/v1/tickets/{ticket_id}",
        payload=payload,
        idempotency_key=build_idempotency_key(req_id, "update"),
    )


async def add_ticket_comment(req_id: str, ticket_id: str, comment: str) -> dict[str, Any]:
    return await _request(
        "comment",
        "POST",
        f"/api/v1/tickets/{ticket_id}/comments",
        payload={"comment": comment},
        idempotency_key=build_idempotency_key(req_id, "comment"),
    )


async def get_operation(operation_id: str) -> dict[str, Any]:
    return await _request("get_operation", "GET", f"/api/v1/operations/{operation_id}")


async def get_ticket(ticket_id: str) -> dict[str, Any]:
    return await _request("get_ticket", "GET", f"/api/v1/tickets/{ticket_id}")


async def find_ticket(ticket_id: str) -> dict[str, Any]:
    return await _request("find_ticket", "POST", f"/api/v1/tickets/{ticket_id}/find")


async def poll_operation(operation_id: str) -> dict[str, Any]:
    settings = get_settings()
    deadline = time.monotonic() + settings.bakery_poll_timeout_seconds
    last_payload: dict[str, Any] | None = None
    while time.monotonic() < deadline:
        payload = await get_operation(operation_id)
        last_payload = payload
        status = str(payload.get("status") or "")
        if status in TERMINAL_OPERATION_STATUSES:
            return payload
        await asyncio.sleep(settings.bakery_poll_interval_seconds)
    if last_payload is None:
        raise TimeoutError("Bakery operation polling timed out without response")
    raise TimeoutError(
        f"Bakery operation polling timed out in status={last_payload.get('status', 'unknown')}"
    )
