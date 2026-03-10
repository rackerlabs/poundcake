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
    CommunicationOpenRequest,
    CommunicationOperationListResponse,
    CommunicationOperationResponse,
    CommunicationResponse,
    CommunicationUpdateRequest,
    TicketCloseRequest,
    TicketCommentRequest,
    TicketCreateRequest,
    TicketUpdateRequest,
)

router = APIRouter(dependencies=[Depends(require_hmac_auth)])


def _map_accepted(ticket_response) -> CommunicationAcceptedResponse:
    return CommunicationAcceptedResponse(
        communication_id=ticket_response.ticket_id,
        operation_id=ticket_response.operation_id,
        action=ticket_response.action,
        status=ticket_response.status,
        created_at=ticket_response.created_at,
    )


def _map_ticket(ticket_response) -> CommunicationResponse:
    return CommunicationResponse(
        communication_id=ticket_response.ticket_id,
        provider_type=ticket_response.provider_type,
        provider_reference_id=ticket_response.provider_ticket_id,
        state=ticket_response.state,
        latest_error=ticket_response.latest_error,
        created_at=ticket_response.created_at,
        updated_at=ticket_response.updated_at,
        data_source=ticket_response.data_source,
        communication_data=ticket_response.ticket_data,
        last_sync_operation_id=ticket_response.last_sync_operation_id,
        last_sync_at=ticket_response.last_sync_at,
    )


def _map_operation(ticket_response) -> CommunicationOperationResponse:
    return CommunicationOperationResponse(
        operation_id=ticket_response.operation_id,
        communication_id=ticket_response.ticket_id,
        action=ticket_response.action,
        status=ticket_response.status,
        attempt_count=ticket_response.attempt_count,
        max_attempts=ticket_response.max_attempts,
        next_attempt_at=ticket_response.next_attempt_at,
        started_at=ticket_response.started_at,
        completed_at=ticket_response.completed_at,
        last_error=ticket_response.last_error,
        provider_response=ticket_response.provider_response,
        created_at=ticket_response.created_at,
        updated_at=ticket_response.updated_at,
    )


@router.post("/communications", response_model=CommunicationAcceptedResponse, status_code=202)
async def open_communication(
    payload: CommunicationOpenRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    db: Session = Depends(get_db),
) -> CommunicationAcceptedResponse:
    accepted = await create_ticket(
        payload=TicketCreateRequest(**payload.model_dump()),
        idempotency_key=idempotency_key,
        db=db,
    )
    return _map_accepted(accepted)


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
    accepted = await update_ticket(
        ticket_id=communication_id,
        payload=TicketUpdateRequest(**payload.model_dump()),
        idempotency_key=idempotency_key,
        db=db,
    )
    return _map_accepted(accepted)


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
    accepted = await add_comment(
        ticket_id=communication_id,
        payload=TicketCommentRequest(
            comment=payload.comment or payload.message or "",
            visibility=payload.visibility,
            context=payload.context,
        ),
        idempotency_key=idempotency_key,
        db=db,
    )
    return _map_accepted(accepted)


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
    accepted = await close_ticket(
        ticket_id=communication_id,
        payload=TicketCloseRequest(**payload.model_dump()),
        idempotency_key=idempotency_key,
        db=db,
    )
    return _map_accepted(accepted)


@router.get("/communications/{communication_id}", response_model=CommunicationResponse)
async def get_communication(
    communication_id: str,
    db: Session = Depends(get_db),
) -> CommunicationResponse:
    ticket = await get_ticket(ticket_id=communication_id, db=db)
    return _map_ticket(ticket)


@router.post("/communications/{communication_id}/sync", response_model=CommunicationResponse)
async def sync_communication(
    communication_id: str,
    db: Session = Depends(get_db),
) -> CommunicationResponse:
    ticket = await find_ticket(ticket_id=communication_id, db=db)
    return _map_ticket(ticket)


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
        communication_id=operations.ticket_id,
        operations=[_map_operation(item) for item in operations.operations],
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
    operation = await get_operation(operation_id=operation_id, db=db)
    return _map_operation(operation)
