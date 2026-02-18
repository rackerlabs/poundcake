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
        provider_type=settings.active_provider,
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
    return TicketResponse(
        ticket_id=ticket.internal_ticket_id,
        provider_type=ticket.provider_type,
        provider_ticket_id=ticket.provider_ticket_id,
        state=ticket.state,
        latest_error=ticket.latest_error,
        created_at=ticket.created_at,
        updated_at=ticket.updated_at,
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
    operations = (
        db.query(TicketOperation)
        .filter(TicketOperation.internal_ticket_id == ticket_id)
        .order_by(TicketOperation.created_at.desc())
        .limit(min(max(limit, 1), 1000))
        .all()
    )
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
