#!/usr/bin/env python3
"""Provider-agnostic communication API endpoints for Bakery."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header
from sqlalchemy.orm import Session

from bakery.api.tickets import (
    add_comment,
    close_ticket,
    create_ticket,
    find_ticket,
    get_operation,
    get_ticket,
    get_ticket_operations,
    update_ticket,
)
from bakery.auth import require_hmac_auth
from bakery.database import get_db
from bakery.schemas import (
    CommunicationAcceptedResponse,
    CommunicationCloseRequest,
    CommunicationNotifyRequest,
    CommunicationCreateRequest,
    CommunicationOperationListResponse,
    CommunicationOperationResponse,
    CommunicationResponse,
    CommunicationUpdateRequest,
)

router = APIRouter(dependencies=[Depends(require_hmac_auth)])


@router.post("/communications", response_model=CommunicationAcceptedResponse, status_code=202)
async def open_communication(
    payload: CommunicationCreateRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    db: Session = Depends(get_db),
) -> CommunicationAcceptedResponse:
    return await create_ticket(payload=payload, idempotency_key=idempotency_key, db=db)


@router.patch(
    "/communications/{communication_id}",
    response_model=CommunicationAcceptedResponse,
    status_code=202,
)
async def update_communication(
    communication_id: str,
    payload: CommunicationUpdateRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    db: Session = Depends(get_db),
) -> CommunicationAcceptedResponse:
    return await update_ticket(
        ticket_id=communication_id,
        payload=payload,
        idempotency_key=idempotency_key,
        db=db,
    )


@router.post(
    "/communications/{communication_id}/notifications",
    response_model=CommunicationAcceptedResponse,
    status_code=202,
)
async def notify_communication(
    communication_id: str,
    payload: CommunicationNotifyRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    db: Session = Depends(get_db),
) -> CommunicationAcceptedResponse:
    return await add_comment(
        ticket_id=communication_id,
        payload=payload,
        idempotency_key=idempotency_key,
        db=db,
    )


@router.post(
    "/communications/{communication_id}/close",
    response_model=CommunicationAcceptedResponse,
    status_code=202,
)
async def close_communication(
    communication_id: str,
    payload: CommunicationCloseRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    db: Session = Depends(get_db),
) -> CommunicationAcceptedResponse:
    return await close_ticket(
        ticket_id=communication_id,
        payload=payload,
        idempotency_key=idempotency_key,
        db=db,
    )


@router.get("/communications/{communication_id}", response_model=CommunicationResponse)
async def get_communication(
    communication_id: str,
    db: Session = Depends(get_db),
) -> CommunicationResponse:
    return await get_ticket(ticket_id=communication_id, db=db)


@router.post("/communications/{communication_id}/sync", response_model=CommunicationResponse)
async def sync_communication(
    communication_id: str,
    db: Session = Depends(get_db),
) -> CommunicationResponse:
    return await find_ticket(ticket_id=communication_id, db=db)


@router.get(
    "/communications/{communication_id}/operations",
    response_model=CommunicationOperationListResponse,
)
async def get_communication_operations(
    communication_id: str,
    limit: int = 100,
    db: Session = Depends(get_db),
) -> CommunicationOperationListResponse:
    operations = await get_ticket_operations(ticket_id=communication_id, limit=limit, db=db)
    return CommunicationOperationListResponse(
        communication_id=operations.communication_id,
        operations=operations.operations,
        count=operations.count,
    )


@router.get(
    "/communications/operations/{operation_id}",
    response_model=CommunicationOperationResponse,
)
async def get_communication_operation(
    operation_id: str,
    db: Session = Depends(get_db),
) -> CommunicationOperationResponse:
    return await get_operation(operation_id=operation_id, db=db)
