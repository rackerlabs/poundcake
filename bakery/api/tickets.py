#!/usr/bin/env python3
"""Ticket management endpoints for Bakery."""

import uuid
from copy import deepcopy
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
import structlog
from sqlalchemy.orm import Session

from bakery.config import settings
from bakery.database import get_db
from bakery.models import TicketRequest, Message, TicketIdMapping
from bakery.schemas import (
    TicketRequestCreate,
    TicketRequestResponse,
    ErrorResponse,
)
from bakery.mixer.factory import get_mixer, list_mixers

router = APIRouter()
logger = structlog.get_logger()


def _get_mapping_by_internal_id(
    db: Session, mixer_type: str, internal_ticket_id: str
) -> TicketIdMapping | None:
    """Resolve internal UUID to external provider ticket ID."""
    return (
        db.query(TicketIdMapping)
        .filter(
            TicketIdMapping.mixer_type == mixer_type,
            TicketIdMapping.internal_ticket_id == internal_ticket_id,
        )
        .first()
    )


def _get_or_create_mapping_for_external_id(
    db: Session, mixer_type: str, external_ticket_id: str
) -> TicketIdMapping:
    """Resolve or create internal UUID mapping for a provider ticket ID."""
    mapping = (
        db.query(TicketIdMapping)
        .filter(
            TicketIdMapping.mixer_type == mixer_type,
            TicketIdMapping.external_ticket_id == external_ticket_id,
        )
        .order_by(TicketIdMapping.id.asc())
        .first()
    )
    if mapping:
        return mapping

    mapping = TicketIdMapping(
        internal_ticket_id=str(uuid.uuid4()),
        mixer_type=mixer_type,
        external_ticket_id=external_ticket_id,
    )
    db.add(mapping)
    db.flush()
    return mapping


def _get_or_create_mapping_for_internal_id(
    db: Session, mixer_type: str, internal_ticket_id: str
) -> TicketIdMapping:
    """Resolve or create mapping by Bakery internal ticket UUID."""
    mapping = _get_mapping_by_internal_id(db, mixer_type, internal_ticket_id)
    if mapping:
        return mapping

    mapping = TicketIdMapping(
        internal_ticket_id=internal_ticket_id,
        mixer_type=mixer_type,
        external_ticket_id=f"dryrun-{internal_ticket_id}",
    )
    db.add(mapping)
    db.flush()
    return mapping


def _build_dry_run_result(
    db: Session,
    ticket_request: TicketRequest,
    request_data: dict,
    original_internal_ticket_id: str | None,
) -> tuple[dict, str | None]:
    """
    Build a dry-run response and skip all outbound ticket-system calls.

    Returns:
        tuple[result_dict, public_ticket_id]
    """
    action = ticket_request.action
    mixer_type = ticket_request.mixer_type

    if action == "create":
        external_ticket_id = f"dryrun-{uuid.uuid4()}"
        mapping = _get_or_create_mapping_for_external_id(db, mixer_type, external_ticket_id)
        return (
            {
                "success": True,
                "ticket_id": mapping.internal_ticket_id,
                "dry_run": True,
                "data": {
                    "action": action,
                    "mixer_type": mixer_type,
                    "outbound_sent": False,
                    "request_data": request_data,
                },
            },
            mapping.internal_ticket_id,
        )

    if action in {"update", "close", "comment"}:
        if not original_internal_ticket_id:
            raise ValueError(
                "request_data.ticket_id (Bakery internal UUID) required for this action"
            )
        internal_id = str(original_internal_ticket_id)
        _get_or_create_mapping_for_internal_id(db, mixer_type, internal_id)
        return (
            {
                "success": True,
                "ticket_id": internal_id,
                "dry_run": True,
                "data": {
                    "action": action,
                    "mixer_type": mixer_type,
                    "outbound_sent": False,
                    "request_data": request_data,
                },
            },
            internal_id,
        )

    if action == "find":
        internal_ticket_id = str(request_data.get("ticket_id", "")).strip()
        if not internal_ticket_id:
            raise ValueError("request_data.ticket_id (Bakery internal UUID) required for find")
        mapping = _get_mapping_by_internal_id(db, mixer_type, internal_ticket_id)
        found = mapping is not None
        result = {
            "success": found,
            "dry_run": True,
            "data": {
                "action": action,
                "mixer_type": mixer_type,
                "found": found,
                "outbound_sent": False,
                "ticket_id": internal_ticket_id,
            },
        }
        if not found:
            result["error"] = f"No ticket mapping found for ticket_id={internal_ticket_id}"
            return result, None
        result["ticket_id"] = internal_ticket_id
        return result, internal_ticket_id

    if action == "search":
        return (
            {
                "success": True,
                "dry_run": True,
                "data": {
                    "action": action,
                    "mixer_type": mixer_type,
                    "outbound_sent": False,
                    "results": [],
                    "request_data": request_data,
                },
            },
            None,
        )

    return (
        {
            "success": False,
            "error": f"Dry-run does not support action '{action}'",
            "dry_run": True,
        },
        None,
    )


async def process_ticket_request(
    request_id: int,
    db_url: str,
) -> None:
    """
    Background task to process ticket request.

    Args:
        request_id: Database ID of ticket request
        db_url: Database URL for creating new session
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    # Create new database session for background task
    engine = create_engine(db_url)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = SessionLocal()

    ticket_request: TicketRequest | None = None

    try:
        # Get request from database
        ticket_request = db.query(TicketRequest).filter(TicketRequest.id == request_id).first()
        if not ticket_request:
            return

        # Update status to processing
        ticket_request.status = "processing"  # type: ignore[assignment]
        db.commit()

        request_data = deepcopy(ticket_request.request_data or {})
        original_internal_ticket_id = request_data.get("ticket_id")
        if settings.ticketing_dry_run:
            logger.info(
                "Bakery dry-run mode: request intercepted",
                correlation_id=ticket_request.correlation_id,
                mixer_type=ticket_request.mixer_type,
                action=ticket_request.action,
                request_data=request_data,
            )
            result, public_ticket_id = _build_dry_run_result(
                db,
                ticket_request,
                request_data,
                str(original_internal_ticket_id) if original_internal_ticket_id else None,
            )
            response_data = deepcopy(result)
            if not public_ticket_id:
                response_data.pop("ticket_id", None)

            message = Message(
                correlation_id=ticket_request.correlation_id,
                ticket_id=public_ticket_id,
                mixer_type=ticket_request.mixer_type,
                status="success" if result.get("success") else "error",
                response_data=response_data,
                error_message=result.get("error"),
            )
            db.add(message)

            ticket_request.status = "success" if result.get("success") else "error"  # type: ignore[assignment]
            ticket_request.ticket_id = public_ticket_id  # type: ignore[assignment]
            ticket_request.error_message = result.get("error")  # type: ignore[assignment]
            ticket_request.completed_at = datetime.now(timezone.utc)  # type: ignore[assignment]
            db.commit()
            return

        # Get appropriate mixer
        mixer = get_mixer(ticket_request.mixer_type)

        if ticket_request.action == "find":
            internal_ticket_id = str(request_data.get("ticket_id", "")).strip()
            if not internal_ticket_id:
                raise ValueError("request_data.ticket_id (Bakery internal UUID) required for find")

            mapping = _get_mapping_by_internal_id(db, ticket_request.mixer_type, internal_ticket_id)
            if not mapping:
                result = {
                    "success": False,
                    "error": f"No ticket mapping found for ticket_id={internal_ticket_id}",
                }
                public_ticket_id = None
            else:
                result = {
                    "success": True,
                    "ticket_id": internal_ticket_id,
                    "data": {
                        "ticket_id": internal_ticket_id,
                        "mixer_type": ticket_request.mixer_type,
                        "found": True,
                    },
                }
                public_ticket_id = internal_ticket_id

            response_data = deepcopy(result)
            if not public_ticket_id:
                response_data.pop("ticket_id", None)

            message = Message(
                correlation_id=ticket_request.correlation_id,
                ticket_id=public_ticket_id,
                mixer_type=ticket_request.mixer_type,
                status="success" if result.get("success") else "error",
                response_data=response_data,
                error_message=result.get("error"),
            )
            db.add(message)

            ticket_request.status = "success" if result.get("success") else "error"  # type: ignore[assignment]
            ticket_request.ticket_id = public_ticket_id  # type: ignore[assignment]
            ticket_request.error_message = result.get("error")  # type: ignore[assignment]
            ticket_request.completed_at = datetime.now(timezone.utc)  # type: ignore[assignment]
            db.commit()
            return

        mixer_action = ticket_request.action

        # Translate Bakery internal UUID to provider ticket ID for mutating actions.
        if mixer_action in {"update", "close", "comment"}:
            if not original_internal_ticket_id:
                raise ValueError(
                    "request_data.ticket_id (Bakery internal UUID) required for this action"
                )
            mapping = _get_mapping_by_internal_id(
                db,
                ticket_request.mixer_type,
                str(original_internal_ticket_id),
            )
            if not mapping:
                raise ValueError(
                    f"No ticket mapping found for ticket_id={original_internal_ticket_id}"
                )
            request_data["ticket_id"] = mapping.external_ticket_id

        # Process request through mixer
        result = await mixer.process_request(
            action=mixer_action,
            data=request_data,
        )
        external_ticket_id = result.get("ticket_id")

        # Expose only Bakery internal UUIDs to PoundCake.
        public_ticket_id: str | None = None
        if result.get("success"):
            if mixer_action == "create":
                if external_ticket_id:
                    mapping = _get_or_create_mapping_for_external_id(
                        db,
                        ticket_request.mixer_type,
                        str(external_ticket_id),
                    )
                    public_ticket_id = mapping.internal_ticket_id
            elif mixer_action in {"update", "close", "comment"}:
                public_ticket_id = str(original_internal_ticket_id)

        response_data = deepcopy(result)
        if public_ticket_id:
            response_data["ticket_id"] = public_ticket_id
        else:
            response_data.pop("ticket_id", None)

        # Create message in queue
        message = Message(
            correlation_id=ticket_request.correlation_id,
            ticket_id=public_ticket_id,
            mixer_type=ticket_request.mixer_type,
            status="success" if result.get("success") else "error",
            response_data=response_data,
            error_message=result.get("error"),
        )
        db.add(message)

        # Update ticket request
        ticket_request.status = "success" if result.get("success") else "error"  # type: ignore[assignment]
        ticket_request.ticket_id = public_ticket_id  # type: ignore[assignment]
        ticket_request.error_message = result.get("error")  # type: ignore[assignment]
        ticket_request.completed_at = datetime.now(timezone.utc)  # type: ignore[assignment]

        db.commit()

    except Exception as e:
        # Log error and update request
        if ticket_request:
            ticket_request.status = "error"  # type: ignore[assignment]
            ticket_request.error_message = str(e)  # type: ignore[assignment]
            ticket_request.completed_at = datetime.now(timezone.utc)  # type: ignore[assignment]

            # Create error message in queue
            message = Message(
                correlation_id=ticket_request.correlation_id,
                mixer_type=ticket_request.mixer_type,
                status="error",
                error_message=str(e),
            )
            db.add(message)
            db.commit()

    finally:
        db.close()


@router.post(
    "/tickets",
    response_model=TicketRequestResponse,
    status_code=202,
    summary="Submit a ticket request",
    description=(
        "Submit a ticket operation for asynchronous processing. "
        "The request is validated and persisted immediately, then processed "
        "in the background by the appropriate mixer. Poll the messages "
        "endpoint with the correlation_id to retrieve the result."
    ),
    responses={
        202: {"description": "Request accepted for processing"},
        400: {"description": "Invalid mixer_type or action", "model": ErrorResponse},
    },
)
async def create_ticket_request(
    request: TicketRequestCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> TicketRequestResponse:
    """
    Create a new ticket request.

    The request is processed asynchronously in the background.
    Results are available via the /messages endpoint.
    """
    # Validate mixer type
    valid_mixer_types = list_mixers()
    if request.mixer_type not in valid_mixer_types:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid mixer_type. Must be one of: {', '.join(valid_mixer_types)}",
        )

    # Validate action
    valid_actions = ["create", "update", "close", "comment", "search", "find"]
    if request.action not in valid_actions:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid action. Must be one of: {', '.join(valid_actions)}",
        )

    # Create ticket request record
    ticket_request = TicketRequest(
        correlation_id=request.correlation_id,
        mixer_type=request.mixer_type,
        action=request.action,
        request_data=request.request_data,
        status="pending",
    )

    db.add(ticket_request)
    db.commit()
    db.refresh(ticket_request)

    # Process in background
    background_tasks.add_task(
        process_ticket_request,
        ticket_request.id,
        settings.database_url,
    )

    return TicketRequestResponse.from_orm(ticket_request)


@router.get(
    "/tickets/{correlation_id}",
    response_model=TicketRequestResponse,
    summary="Get ticket request status",
    description="Retrieve the current status of a ticket request by its correlation ID.",
    responses={
        200: {"description": "Ticket request found"},
        404: {"description": "Ticket request not found", "model": ErrorResponse},
    },
)
async def get_ticket_request(
    correlation_id: str,
    db: Session = Depends(get_db),
) -> TicketRequestResponse:
    """Get ticket request by correlation ID."""
    ticket_request = (
        db.query(TicketRequest).filter(TicketRequest.correlation_id == correlation_id).first()
    )

    if not ticket_request:
        raise HTTPException(status_code=404, detail="Ticket request not found")

    return TicketRequestResponse.from_orm(ticket_request)
