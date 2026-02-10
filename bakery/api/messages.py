#!/usr/bin/env python3
"""Message queue endpoints for Bakery."""

from datetime import datetime, timezone, timedelta
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from bakery.config import settings
from bakery.database import get_db
from bakery.models import Message
from bakery.schemas import MessageListResponse, MessageResponse, SuccessResponse

router = APIRouter()


@router.get(
    "/messages",
    response_model=MessageListResponse,
    summary="Poll for response messages",
    description=(
        "Retrieve unretrieved messages from the response queue. Messages are "
        "marked as retrieved once returned, so subsequent polls will not "
        "include them. Use correlation_id to get the result for a specific "
        "ticket request."
    ),
)
async def get_messages(
    correlation_id: Optional[str] = Query(None, description="Filter by correlation ID"),
    mixer_type: Optional[str] = Query(None, description="Filter by mixer type"),
    status: Optional[str] = Query(None, description="Filter by status (success, error)"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum number of messages to return"),
    db: Session = Depends(get_db),
) -> MessageListResponse:
    """Poll for messages from the response queue."""
    # Build query
    query = db.query(Message).filter(Message.retrieved_at.is_(None))

    # Apply filters
    if correlation_id:
        query = query.filter(Message.correlation_id == correlation_id)
    if mixer_type:
        query = query.filter(Message.mixer_type == mixer_type)
    if status:
        query = query.filter(Message.status == status)

    # Get messages ordered by creation time
    messages = query.order_by(Message.created_at.asc()).limit(limit).all()

    # Mark messages as retrieved
    for message in messages:
        message.retrieved_at = datetime.now(timezone.utc)  # type: ignore[assignment]
    db.commit()

    return MessageListResponse(
        messages=[MessageResponse.from_orm(msg) for msg in messages],
        count=len(messages),
    )


@router.delete(
    "/messages/{message_id}",
    response_model=SuccessResponse,
    summary="Delete a message",
    description="Delete a specific message from the response queue by its ID.",
    responses={
        200: {"description": "Message deleted"},
        404: {"description": "Message not found"},
    },
)
async def delete_message(
    message_id: int,
    db: Session = Depends(get_db),
) -> SuccessResponse:
    """Delete a message from the queue."""
    message = db.query(Message).filter(Message.id == message_id).first()
    if not message:
        raise HTTPException(status_code=404, detail="Message not found")

    db.delete(message)
    db.commit()

    return SuccessResponse(
        message="Message deleted successfully",
        data={"message_id": message_id},
    )


@router.post(
    "/messages/cleanup",
    response_model=SuccessResponse,
    summary="Clean up old messages",
    description=(
        "Delete retrieved messages older than the configured retention period "
        "(MESSAGE_RETENTION_HOURS, default 24h). Only messages that have "
        "already been retrieved are eligible for cleanup."
    ),
)
async def cleanup_old_messages(
    db: Session = Depends(get_db),
) -> SuccessResponse:
    """Clean up old retrieved messages."""
    cutoff_time = datetime.now(timezone.utc) - timedelta(hours=settings.message_retention_hours)

    # Delete old retrieved messages
    deleted_count = (
        db.query(Message)
        .filter(
            Message.retrieved_at.isnot(None),
            Message.created_at < cutoff_time,
        )
        .delete()
    )

    db.commit()

    return SuccessResponse(
        message=f"Cleaned up {deleted_count} old messages",
        data={"deleted_count": deleted_count},
    )
