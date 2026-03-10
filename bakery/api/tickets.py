#!/usr/bin/env python3
"""New ticketing API endpoints for Bakery."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from bakery.auth import require_hmac_auth
from bakery.config import settings
from bakery.database import get_db
from bakery.mixer.factory import get_mixer
from bakery.metrics import BAKERY_OPERATIONS_TOTAL
from bakery.models import IdempotencyKey, Ticket, TicketOperation
from bakery.schemas import (
    OperationAcceptedResponse,
    TicketCloseRequest,
    TicketCommentRequest,
    TicketCreateRequest,
    TicketOperationListResponse,
    TicketOperationResponse,
    TicketResponse,
    TicketUpdateRequest,
)

router = APIRouter(dependencies=[Depends(require_hmac_auth)])


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _is_non_empty(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, dict)):
        return len(value) > 0
    return True


def _first_non_empty(*values: Any) -> Any:
    for value in values:
        if _is_non_empty(value):
            return value
    return None


def _stringify(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        cleaned = value.strip()
        return cleaned or None
    as_text = str(value).strip()
    return as_text or None


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    return {}


def _canonical_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _assert_idempotency_key(value: str | None) -> str:
    if not value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Idempotency-Key header is required",
        )
    return value.strip()


def _op_response(operation: TicketOperation) -> TicketOperationResponse:
    return TicketOperationResponse(
        operation_id=operation.operation_id,
        ticket_id=operation.internal_ticket_id,
        action=operation.action,
        status=operation.status,
        attempt_count=operation.attempt_count,
        max_attempts=operation.max_attempts,
        next_attempt_at=operation.next_attempt_at,
        started_at=operation.started_at,
        completed_at=operation.completed_at,
        last_error=operation.last_error,
        provider_response=operation.provider_response,
        created_at=operation.created_at,
        updated_at=operation.updated_at,
    )


def _accepted(operation: TicketOperation) -> OperationAcceptedResponse:
    return OperationAcceptedResponse(
        ticket_id=operation.internal_ticket_id,
        operation_id=operation.operation_id,
        action=operation.action,
        status=operation.status,
        created_at=operation.created_at,
    )


def _resolve_idempotency(
    db: Session,
    idempotency_key: str,
    action: str,
    scope: str,
    request_hash: str,
) -> IdempotencyKey | None:
    existing = (
        db.query(IdempotencyKey)
        .filter(
            IdempotencyKey.idempotency_key == idempotency_key,
            IdempotencyKey.action == action,
            IdempotencyKey.ticket_scope == scope,
        )
        .first()
    )
    if not existing:
        return None
    if existing.request_hash != request_hash:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Idempotency-Key reused with different payload",
        )
    return existing


def _load_ticket_operations(
    db: Session,
    ticket_id: str,
    *,
    limit: int = 1000,
) -> list[TicketOperation]:
    return (
        db.query(TicketOperation)
        .filter(TicketOperation.internal_ticket_id == ticket_id)
        .order_by(TicketOperation.created_at.desc())
        .limit(min(max(limit, 1), 1000))
        .all()
    )


def _operation_payload(operation: TicketOperation) -> dict[str, Any]:
    normalized = _as_dict(operation.normalized_payload)
    if normalized:
        return normalized
    return _as_dict(operation.request_payload)


def _context_maps(payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    context = payload.get("context")
    context_map = context if isinstance(context, dict) else {}
    labels = context_map.get("labels")
    labels_map = labels if isinstance(labels, dict) else {}
    annotations = context_map.get("annotations")
    annotations_map = annotations if isinstance(annotations, dict) else {}
    return context_map, labels_map, annotations_map


def _requested_provider_type(payload: dict[str, Any]) -> str:
    context_map, _, _ = _context_maps(payload)
    provider = _stringify(
        _first_non_empty(
            payload.get("provider_type"),
            context_map.get("provider_type"),
            context_map.get("execution_target"),
        )
    )
    return str(provider or settings.active_provider or "rackspace_core").strip().lower()


def _lookup_payload_value(payload: dict[str, Any], keys: list[str]) -> str | None:
    context_map, labels_map, annotations_map = _context_maps(payload)
    for key in keys:
        value = _first_non_empty(
            payload.get(key),
            context_map.get(key),
            labels_map.get(key),
            annotations_map.get(key),
        )
        as_text = _stringify(value)
        if as_text is not None:
            return as_text
    return None


def _lookup_operation_value(operations: list[TicketOperation], keys: list[str]) -> str | None:
    for operation in operations:
        value = _lookup_payload_value(_operation_payload(operation), keys)
        if value is not None:
            return value
    return None


def _result_ticket_id(provider: str, row: dict[str, Any]) -> str | None:
    if provider == "servicenow":
        return _stringify(_first_non_empty(row.get("number"), row.get("sys_id"), row.get("id")))
    if provider == "jira":
        return _stringify(_first_non_empty(row.get("key"), row.get("id")))
    if provider == "github":
        return _stringify(_first_non_empty(row.get("number"), row.get("id")))
    if provider == "pagerduty":
        return _stringify(_first_non_empty(row.get("id"), row.get("incident_number")))
    if provider == "rackspace_core":
        return _stringify(
            _first_non_empty(
                row.get("ticket_number"),
                row.get("number"),
                row.get("id"),
            )
        )
    return None


def _select_provider_ticket(
    provider: str,
    provider_ticket_id: str | None,
    provider_response: dict[str, Any],
) -> dict[str, Any] | None:
    data = provider_response.get("data")
    if not isinstance(data, dict):
        return None
    rows = data.get("results")
    if not isinstance(rows, list):
        return None

    expected = _stringify(provider_ticket_id)
    for row in rows:
        if not isinstance(row, dict):
            continue
        if expected is None:
            return row
        row_ticket_id = _result_ticket_id(provider, row)
        if row_ticket_id is not None and row_ticket_id == expected:
            return row

    if expected is None:
        for row in rows:
            if isinstance(row, dict):
                return row
    return None


def _latest_find_operation(operations: list[TicketOperation]) -> TicketOperation | None:
    for operation in operations:
        if operation.action == "find" and operation.status == "succeeded":
            return operation
    return None


def _build_local_ticket_data(ticket: Ticket, operations: list[TicketOperation]) -> dict[str, Any]:
    projection: dict[str, Any] = {
        "ticket_id": ticket.internal_ticket_id,
        "provider_type": ticket.provider_type,
        "provider_ticket_id": ticket.provider_ticket_id,
        "state": ticket.state,
        "comments": [],
    }

    sorted_ops = list(reversed(operations))
    last_payload: dict[str, Any] | None = None
    last_provider_response: dict[str, Any] | None = None

    for operation in sorted_ops:
        if operation.status != "succeeded":
            continue
        payload = _operation_payload(operation)
        action = operation.action

        if payload:
            last_payload = payload

        if action == "create":
            title = _first_non_empty(payload.get("title"), payload.get("subject"))
            description = _first_non_empty(payload.get("description"), payload.get("body"))
            severity = payload.get("severity")
            category = payload.get("category")
            source = payload.get("source")

            if _is_non_empty(title):
                projection["title"] = title
            if _is_non_empty(description):
                projection["description"] = description
            if _is_non_empty(severity):
                projection["severity"] = severity
            if _is_non_empty(category):
                projection["category"] = category
            if _is_non_empty(source):
                projection["source"] = source

        elif action == "update":
            updates = payload.get("updates")
            if not isinstance(updates, dict):
                updates = payload.get("attributes")
            if not isinstance(updates, dict):
                updates = {}
                for key in ("title", "description", "severity", "category", "state"):
                    if payload.get(key) is not None:
                        updates[key] = payload.get(key)

            for key in ("title", "description", "severity", "category", "state"):
                if updates.get(key) is not None:
                    projection[key] = updates[key]
            if updates.get("subject") is not None:
                projection["title"] = updates["subject"]
            if updates.get("body") is not None:
                projection["description"] = updates["body"]

        elif action == "comment":
            comment_text = payload.get("comment")
            if _is_non_empty(comment_text):
                projection["comments"].append(
                    {
                        "comment": comment_text,
                        "visibility": payload.get("visibility"),
                        "created_at": operation.completed_at or operation.created_at,
                    }
                )

        elif action == "close":
            close_state = _first_non_empty(payload.get("state"), payload.get("status"))
            if _is_non_empty(close_state):
                projection["state"] = close_state
            resolution_notes = _first_non_empty(
                payload.get("resolution_notes"),
                payload.get("close_notes"),
            )
            if _is_non_empty(resolution_notes):
                projection["resolution_notes"] = resolution_notes
            resolution_code = payload.get("resolution_code")
            if _is_non_empty(resolution_code):
                projection["resolution_code"] = resolution_code

        if isinstance(operation.provider_response, dict):
            last_provider_response = operation.provider_response
            if operation.action == "find":
                provider_ticket = _select_provider_ticket(
                    ticket.provider_type,
                    ticket.provider_ticket_id,
                    operation.provider_response,
                )
                if provider_ticket is not None:
                    projection["provider_ticket"] = provider_ticket

    if not projection["comments"]:
        projection.pop("comments", None)
    if last_payload is not None:
        projection["last_provider_payload"] = last_payload
    if last_provider_response is not None:
        projection["last_provider_response"] = last_provider_response

    return projection


def _build_provider_find_payload(
    ticket: Ticket, operations: list[TicketOperation]
) -> dict[str, Any]:
    provider_ticket_id = _stringify(ticket.provider_ticket_id)
    if provider_ticket_id is None:
        raise ValueError("Provider ticket id is not available yet for this ticket")

    provider = str(ticket.provider_type or settings.active_provider or "").strip().lower()
    if provider == "rackspace_core":
        return {"ticket_number": provider_ticket_id}
    if provider == "servicenow":
        return {"query": f"number={provider_ticket_id}", "limit": 1, "offset": 0}
    if provider == "jira":
        escaped = provider_ticket_id.replace('"', '\\"')
        return {"jql": f'key = "{escaped}"', "limit": 1, "offset": 0}
    if provider == "github":
        owner = _lookup_operation_value(operations, ["owner", "githubOwner"])
        repo = _lookup_operation_value(operations, ["repo", "githubRepo"])
        if owner is None or repo is None:
            raise ValueError("GitHub owner/repo metadata is required to find provider ticket")
        return {
            "owner": owner,
            "repo": repo,
            "query": f"number:{provider_ticket_id}",
            "state": "all",
            "limit": 20,
            "page": 1,
        }
    if provider == "pagerduty":
        return {
            "statuses": ["triggered", "acknowledged", "resolved"],
            "limit": 100,
            "offset": 0,
        }
    raise ValueError(f"Unsupported provider for find operation: {provider}")


def _record_find_operation(
    db: Session,
    ticket_id: str,
    status_value: str,
    request_payload: dict[str, Any],
    normalized_payload: dict[str, Any],
    provider_response: dict[str, Any] | None = None,
    last_error: str | None = None,
) -> TicketOperation:
    now = _now()
    operation = TicketOperation(
        operation_id=str(uuid.uuid4()),
        internal_ticket_id=ticket_id,
        action="find",
        status=status_value,
        request_payload=request_payload,
        normalized_payload=normalized_payload,
        provider_response=provider_response,
        last_error=last_error,
        attempt_count=1,
        max_attempts=1,
        next_attempt_at=None,
        started_at=now,
        completed_at=now,
        created_at=now,
        updated_at=now,
    )
    db.add(operation)
    db.flush()
    return operation


def _ticket_response(
    ticket: Ticket,
    operations: list[TicketOperation],
    *,
    data_source: str,
    last_sync_operation: TicketOperation | None,
) -> TicketResponse:
    return TicketResponse(
        ticket_id=ticket.internal_ticket_id,
        provider_type=ticket.provider_type,
        provider_ticket_id=ticket.provider_ticket_id,
        state=ticket.state,
        latest_error=ticket.latest_error,
        created_at=ticket.created_at,
        updated_at=ticket.updated_at,
        data_source=data_source,
        ticket_data=_build_local_ticket_data(ticket, operations),
        last_sync_operation_id=(
            last_sync_operation.operation_id if last_sync_operation is not None else None
        ),
        last_sync_at=last_sync_operation.completed_at if last_sync_operation is not None else None,
    )


@router.post("/tickets", response_model=OperationAcceptedResponse, status_code=202)
async def create_ticket(
    payload: TicketCreateRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    db: Session = Depends(get_db),
) -> OperationAcceptedResponse:
    key = _assert_idempotency_key(idempotency_key)
    request_payload = payload.model_dump()
    request_hash = _canonical_hash(request_payload)
    scope = "global"

    existing = _resolve_idempotency(db, key, "create", scope, request_hash)
    if existing:
        op = (
            db.query(TicketOperation)
            .filter(TicketOperation.operation_id == existing.operation_id)
            .first()
        )
        if not op:
            raise HTTPException(status_code=500, detail="Idempotency record is inconsistent")
        BAKERY_OPERATIONS_TOTAL.labels(action="create", status="deduplicated").inc()
        return _accepted(op)

    now = datetime.now(timezone.utc)
    internal_ticket_id = str(uuid.uuid4())
    operation_id = str(uuid.uuid4())

    ticket = Ticket(
        internal_ticket_id=internal_ticket_id,
        provider_type=_requested_provider_type(request_payload),
        state="queued",
        created_at=now,
        updated_at=now,
    )
    operation = TicketOperation(
        operation_id=operation_id,
        internal_ticket_id=internal_ticket_id,
        action="create",
        status="queued",
        request_payload=request_payload,
        normalized_payload=request_payload,
        attempt_count=0,
        max_attempts=settings.worker_max_attempts,
        next_attempt_at=now,
        created_at=now,
        updated_at=now,
    )
    idem = IdempotencyKey(
        idempotency_key=key,
        action="create",
        ticket_scope=scope,
        request_hash=request_hash,
        operation_id=operation_id,
        created_at=now,
    )

    db.add(ticket)
    db.add(operation)
    db.add(idem)
    db.commit()
    db.refresh(operation)
    BAKERY_OPERATIONS_TOTAL.labels(action="create", status="queued").inc()
    return _accepted(operation)


def _enqueue_ticket_action(
    db: Session,
    ticket_id: str,
    action: str,
    request_payload: dict[str, Any],
    idempotency_key: str,
) -> OperationAcceptedResponse:
    ticket = db.query(Ticket).filter(Ticket.internal_ticket_id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")

    request_hash = _canonical_hash(request_payload)
    scope = ticket_id
    existing = _resolve_idempotency(db, idempotency_key, action, scope, request_hash)
    if existing:
        op = (
            db.query(TicketOperation)
            .filter(TicketOperation.operation_id == existing.operation_id)
            .first()
        )
        if not op:
            raise HTTPException(status_code=500, detail="Idempotency record is inconsistent")
        BAKERY_OPERATIONS_TOTAL.labels(action=action, status="deduplicated").inc()
        return _accepted(op)

    now = datetime.now(timezone.utc)
    operation_id = str(uuid.uuid4())
    operation = TicketOperation(
        operation_id=operation_id,
        internal_ticket_id=ticket_id,
        action=action,
        status="queued",
        request_payload=request_payload,
        normalized_payload=request_payload,
        attempt_count=0,
        max_attempts=settings.worker_max_attempts,
        next_attempt_at=now,
        created_at=now,
        updated_at=now,
    )
    idem = IdempotencyKey(
        idempotency_key=idempotency_key,
        action=action,
        ticket_scope=scope,
        request_hash=request_hash,
        operation_id=operation_id,
        created_at=now,
    )
    db.add(operation)
    db.add(idem)
    db.commit()
    db.refresh(operation)
    BAKERY_OPERATIONS_TOTAL.labels(action=action, status="queued").inc()
    return _accepted(operation)


@router.patch("/tickets/{ticket_id}", response_model=OperationAcceptedResponse, status_code=202)
async def update_ticket(
    ticket_id: str,
    payload: TicketUpdateRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    db: Session = Depends(get_db),
) -> OperationAcceptedResponse:
    key = _assert_idempotency_key(idempotency_key)
    return _enqueue_ticket_action(db, ticket_id, "update", payload.model_dump(), key)


@router.post(
    "/tickets/{ticket_id}/comments", response_model=OperationAcceptedResponse, status_code=202
)
async def add_comment(
    ticket_id: str,
    payload: TicketCommentRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    db: Session = Depends(get_db),
) -> OperationAcceptedResponse:
    key = _assert_idempotency_key(idempotency_key)
    return _enqueue_ticket_action(db, ticket_id, "comment", payload.model_dump(), key)


@router.post(
    "/tickets/{ticket_id}/close", response_model=OperationAcceptedResponse, status_code=202
)
async def close_ticket(
    ticket_id: str,
    payload: TicketCloseRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    db: Session = Depends(get_db),
) -> OperationAcceptedResponse:
    key = _assert_idempotency_key(idempotency_key)
    return _enqueue_ticket_action(db, ticket_id, "close", payload.model_dump(), key)


@router.get("/tickets/{ticket_id}", response_model=TicketResponse)
async def get_ticket(ticket_id: str, db: Session = Depends(get_db)) -> TicketResponse:
    ticket = db.query(Ticket).filter(Ticket.internal_ticket_id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    operations = _load_ticket_operations(db, ticket_id, limit=500)
    last_sync = _latest_find_operation(operations)
    return _ticket_response(
        ticket,
        operations,
        data_source="local_cache",
        last_sync_operation=last_sync,
    )


@router.post("/tickets/{ticket_id}/find", response_model=TicketResponse)
async def find_ticket(ticket_id: str, db: Session = Depends(get_db)) -> TicketResponse:
    ticket = db.query(Ticket).filter(Ticket.internal_ticket_id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")

    operations = _load_ticket_operations(db, ticket_id, limit=500)
    request_payload: dict[str, Any] = {"ticket_id": ticket.internal_ticket_id}

    if settings.ticketing_dry_run:
        response_payload = {
            "success": True,
            "ticket_id": ticket.provider_ticket_id or f"dryrun-{ticket.internal_ticket_id}",
            "data": {
                "dry_run": True,
                "source": "local_cache",
                "ticket": _build_local_ticket_data(ticket, operations),
            },
        }
        sync_op = _record_find_operation(
            db,
            ticket_id=ticket.internal_ticket_id,
            status_value="succeeded",
            request_payload=request_payload,
            normalized_payload=request_payload,
            provider_response=response_payload,
            last_error=None,
        )
        ticket.latest_error = None
        ticket.updated_at = _now()
        db.commit()
        db.refresh(ticket)
        db.refresh(sync_op)
        BAKERY_OPERATIONS_TOTAL.labels(action="find", status="succeeded").inc()
        operations = _load_ticket_operations(db, ticket_id, limit=500)
        return _ticket_response(
            ticket,
            operations,
            data_source="dry_run_local_cache",
            last_sync_operation=sync_op,
        )

    try:
        search_payload = _build_provider_find_payload(ticket, operations)
    except ValueError as exc:
        error_message = str(exc)
        response_payload = {
            "success": False,
            "error": error_message,
            "data": {"source": "local_cache"},
        }
        sync_op = _record_find_operation(
            db,
            ticket_id=ticket.internal_ticket_id,
            status_value="failed",
            request_payload=request_payload,
            normalized_payload=request_payload,
            provider_response=response_payload,
            last_error=error_message,
        )
        ticket.latest_error = error_message
        ticket.updated_at = _now()
        db.commit()
        db.refresh(ticket)
        db.refresh(sync_op)
        BAKERY_OPERATIONS_TOTAL.labels(action="find", status="failed").inc()
        operations = _load_ticket_operations(db, ticket_id, limit=500)
        return _ticket_response(
            ticket,
            operations,
            data_source="local_cache",
            last_sync_operation=sync_op,
        )

    provider = str(ticket.provider_type or settings.active_provider or "").strip().lower()
    mixer = get_mixer(provider)
    provider_response = await mixer.process_request("search", search_payload)
    if not isinstance(provider_response, dict):
        provider_response = {"success": False, "error": "Provider returned non-dict response"}

    matched_ticket = _select_provider_ticket(
        provider,
        ticket.provider_ticket_id,
        provider_response,
    )

    data = provider_response.get("data")
    if isinstance(data, dict):
        data["matched_ticket"] = matched_ticket

    is_success = bool(provider_response.get("success"))
    status_value = "succeeded" if is_success else "failed"
    error_message = (
        None if is_success else str(provider_response.get("error") or "provider find failed")
    )
    sync_op = _record_find_operation(
        db,
        ticket_id=ticket.internal_ticket_id,
        status_value=status_value,
        request_payload=request_payload,
        normalized_payload=search_payload,
        provider_response=provider_response,
        last_error=error_message,
    )
    ticket.latest_error = error_message
    ticket.updated_at = _now()
    db.commit()
    db.refresh(ticket)
    db.refresh(sync_op)
    BAKERY_OPERATIONS_TOTAL.labels(action="find", status=status_value).inc()

    operations = _load_ticket_operations(db, ticket_id, limit=500)
    data_source = "provider" if is_success else "local_cache"
    return _ticket_response(
        ticket,
        operations,
        data_source=data_source,
        last_sync_operation=sync_op if is_success else _latest_find_operation(operations),
    )


@router.get("/tickets/{ticket_id}/operations", response_model=TicketOperationListResponse)
async def get_ticket_operations(
    ticket_id: str,
    limit: int = 100,
    db: Session = Depends(get_db),
) -> TicketOperationListResponse:
    ticket = db.query(Ticket).filter(Ticket.internal_ticket_id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    operations = _load_ticket_operations(db, ticket_id, limit=limit)
    return TicketOperationListResponse(
        ticket_id=ticket_id,
        operations=[_op_response(op) for op in operations],
        count=len(operations),
    )


@router.get("/operations/{operation_id}", response_model=TicketOperationResponse)
async def get_operation(
    operation_id: str, db: Session = Depends(get_db)
) -> TicketOperationResponse:
    operation = (
        db.query(TicketOperation).filter(TicketOperation.operation_id == operation_id).first()
    )
    if not operation:
        raise HTTPException(status_code=404, detail="Operation not found")
    return _op_response(operation)
