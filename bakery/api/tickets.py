#!/usr/bin/env python3
"""Ticket management endpoints for Bakery."""

import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session

from bakery.database import get_db
from bakery.models import TicketRequest, Message
from bakery.schemas import (
    TicketRequestCreate,
    TicketRequestResponse,
    ErrorResponse,
)
from bakery.adapters.factory import get_adapter

router = APIRouter()


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

    try:
        # Get request from database
        ticket_request = (
            db.query(TicketRequest).filter(TicketRequest.id == request_id).first()
        )
        if not ticket_request:
            return

        # Update status to processing
        ticket_request.status = "processing"  # type: ignore[assignment]
        db.commit()

        # Get appropriate adapter
        adapter = get_adapter(ticket_request.adapter_type)

        # Process request through adapter
        result = await adapter.process_request(
            action=ticket_request.action,
            data=ticket_request.request_data,
        )

        # Create message in queue
        message = Message(
            correlation_id=ticket_request.correlation_id,
            ticket_id=result.get("ticket_id"),
            adapter_type=ticket_request.adapter_type,
            status="success" if result.get("success") else "error",
            response_data=result,
            error_message=result.get("error"),
        )
        db.add(message)

        # Update ticket request
        ticket_request.status = "success" if result.get("success") else "error"  # type: ignore[assignment]
        ticket_request.ticket_id = result.get("ticket_id")  # type: ignore[assignment]
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
                adapter_type=ticket_request.adapter_type,
                status="error",
                error_message=str(e),
            )
            db.add(message)
            db.commit()

    finally:
        db.close()


@router.post("/tickets", response_model=TicketRequestResponse, status_code=202)
async def create_ticket_request(
    request: TicketRequestCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> TicketRequestResponse:
    """
    Create a new ticket request.

    The request is processed asynchronously in the background.
    Results are available via the /messages endpoint.

    Args:
        request: Ticket request data
        background_tasks: FastAPI background tasks
        db: Database session

    Returns:
        Created ticket request with status "pending"

    Raises:
        HTTPException: If adapter type is invalid
    """
    # Validate adapter type
    valid_adapters = ["servicenow", "jira", "github", "pagerduty", "rackspace_core"]
    if request.adapter_type not in valid_adapters:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid adapter_type. Must be one of: {', '.join(valid_adapters)}",
        )

    # Create ticket request record
    ticket_request = TicketRequest(
        correlation_id=request.correlation_id,
        adapter_type=request.adapter_type,
        action=request.action,
        request_data=request.request_data,
        status="pending",
    )

    db.add(ticket_request)
    db.commit()
    db.refresh(ticket_request)

    # Process in background
    from bakery.config import settings

    background_tasks.add_task(
        process_ticket_request,
        ticket_request.id,
        settings.database_url,
    )

    return TicketRequestResponse.from_orm(ticket_request)


@router.get("/tickets/{correlation_id}", response_model=TicketRequestResponse)
async def get_ticket_request(
    correlation_id: str,
    db: Session = Depends(get_db),
) -> TicketRequestResponse:
    """
    Get ticket request by correlation ID.

    Args:
        correlation_id: Correlation ID of request
        db: Database session

    Returns:
        Ticket request details

    Raises:
        HTTPException: If request not found
    """
    ticket_request = (
        db.query(TicketRequest)
        .filter(TicketRequest.correlation_id == correlation_id)
        .first()
    )

    if not ticket_request:
        raise HTTPException(status_code=404, detail="Ticket request not found")

    return TicketRequestResponse.from_orm(ticket_request)
