"""Bakery client for PoundCake communication operations."""

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
from contracts.communications import (
    CommunicationAcceptedResponse,
    CommunicationOperationResponse,
    CommunicationResponse,
)
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
) -> Any:
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


async def open_communication(req_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    return await open_communication_with_key(req_id=req_id, payload=payload, idempotency_key=None)


async def open_communication_with_key(
    req_id: str, payload: dict[str, Any], idempotency_key: str | None
) -> dict[str, Any]:
    response = await _request(
        "open",
        "POST",
        "/api/v1/communications",
        payload=payload,
        idempotency_key=idempotency_key or build_idempotency_key(req_id, "open"),
    )
    return CommunicationAcceptedResponse.model_validate(response).model_dump()


async def close_communication(
    req_id: str, communication_id: str, payload: dict[str, Any]
) -> dict[str, Any]:
    return await close_communication_with_key(
        req_id=req_id,
        communication_id=communication_id,
        payload=payload,
        idempotency_key=None,
    )


async def close_communication_with_key(
    req_id: str,
    communication_id: str,
    payload: dict[str, Any],
    idempotency_key: str | None,
) -> dict[str, Any]:
    response = await _request(
        "close",
        "POST",
        f"/api/v1/communications/{communication_id}/close",
        payload=payload,
        idempotency_key=idempotency_key or build_idempotency_key(req_id, "close"),
    )
    return CommunicationAcceptedResponse.model_validate(response).model_dump()


async def update_communication(
    req_id: str, communication_id: str, payload: dict[str, Any]
) -> dict[str, Any]:
    return await update_communication_with_key(
        req_id=req_id,
        communication_id=communication_id,
        payload=payload,
        idempotency_key=None,
    )


async def update_communication_with_key(
    req_id: str,
    communication_id: str,
    payload: dict[str, Any],
    idempotency_key: str | None,
) -> dict[str, Any]:
    response = await _request(
        "update",
        "PATCH",
        f"/api/v1/communications/{communication_id}",
        payload=payload,
        idempotency_key=idempotency_key or build_idempotency_key(req_id, "update"),
    )
    return CommunicationAcceptedResponse.model_validate(response).model_dump()


async def notify_communication(
    req_id: str, communication_id: str, payload: dict[str, Any]
) -> dict[str, Any]:
    return await notify_communication_with_key(
        req_id=req_id,
        communication_id=communication_id,
        payload=payload,
        idempotency_key=None,
    )


async def notify_communication_with_key(
    req_id: str,
    communication_id: str,
    payload: dict[str, Any],
    idempotency_key: str | None,
) -> dict[str, Any]:
    response = await _request(
        "notify",
        "POST",
        f"/api/v1/communications/{communication_id}/notifications",
        payload=payload,
        idempotency_key=idempotency_key or build_idempotency_key(req_id, "notify"),
    )
    return CommunicationAcceptedResponse.model_validate(response).model_dump()


async def get_communication(communication_id: str) -> dict[str, Any]:
    response = await _request(
        "get_communication", "GET", f"/api/v1/communications/{communication_id}"
    )
    return CommunicationResponse.model_validate(response).model_dump()


async def sync_communication(communication_id: str) -> dict[str, Any]:
    response = await _request(
        "sync_communication",
        "POST",
        f"/api/v1/communications/{communication_id}/sync",
    )
    return CommunicationResponse.model_validate(response).model_dump()


async def get_communication_operation(operation_id: str) -> dict[str, Any]:
    response = await _request(
        "get_communication_operation",
        "GET",
        f"/api/v1/communications/operations/{operation_id}",
    )
    return CommunicationOperationResponse.model_validate(response).model_dump()


async def create_ticket(req_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    return await create_ticket_with_key(req_id=req_id, payload=payload, idempotency_key=None)


async def create_ticket_with_key(
    req_id: str, payload: dict[str, Any], idempotency_key: str | None
) -> dict[str, Any]:
    return await open_communication_with_key(
        req_id=req_id,
        payload=payload,
        idempotency_key=idempotency_key,
    )


async def close_ticket(req_id: str, ticket_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    return await close_ticket_with_key(
        req_id=req_id, ticket_id=ticket_id, payload=payload, idempotency_key=None
    )


async def close_ticket_with_key(
    req_id: str, ticket_id: str, payload: dict[str, Any], idempotency_key: str | None
) -> dict[str, Any]:
    return await close_communication_with_key(
        req_id=req_id,
        communication_id=ticket_id,
        payload=payload,
        idempotency_key=idempotency_key,
    )


async def update_ticket(req_id: str, ticket_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    return await update_ticket_with_key(
        req_id=req_id, ticket_id=ticket_id, payload=payload, idempotency_key=None
    )


async def update_ticket_with_key(
    req_id: str, ticket_id: str, payload: dict[str, Any], idempotency_key: str | None
) -> dict[str, Any]:
    return await update_communication_with_key(
        req_id=req_id,
        communication_id=ticket_id,
        payload=payload,
        idempotency_key=idempotency_key,
    )


async def add_ticket_comment(req_id: str, ticket_id: str, comment: str) -> dict[str, Any]:
    return await add_ticket_comment_with_key(
        req_id=req_id, ticket_id=ticket_id, payload={"message": comment}, idempotency_key=None
    )


async def add_ticket_comment_with_key(
    req_id: str,
    ticket_id: str,
    payload: dict[str, Any],
    idempotency_key: str | None,
) -> dict[str, Any]:
    return await notify_communication_with_key(
        req_id=req_id,
        communication_id=ticket_id,
        payload=payload,
        idempotency_key=idempotency_key,
    )


async def get_operation(operation_id: str) -> dict[str, Any]:
    return await get_communication_operation(operation_id)


async def get_ticket(ticket_id: str) -> dict[str, Any]:
    return await get_communication(ticket_id)


async def find_ticket(ticket_id: str) -> dict[str, Any]:
    return await sync_communication(ticket_id)


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
