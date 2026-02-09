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


@router.get("/messages", response_model=MessageListResponse)
async def get_messages(
    correlation_id: Optional[str] = Query(
        None, description="Filter by correlation ID"
    ),
    adapter_type: Optional[str] = Query(None, description="Filter by adapter type"),
    status: Optional[str] = Query(None, description="Filter by status"),
    limit: int = Query(
        100, ge=1, le=1000, description="Maximum number of messages to return"
    ),
    db: Session = Depends(get_db),
) -> MessageListResponse:
    """
    Poll for messages from the queue.

    Args:
        correlation_id: Optional correlation ID filter
        adapter_type: Optional adapter type filter
        status: Optional status filter
        limit: Maximum messages to return
        db: Database session

    Returns:
        List of messages matching filters
    """
    # Build query
    query = db.query(Message).filter(Message.retrieved_at.is_(None))

    # Apply filters
    if correlation_id:
        query = query.filter(Message.correlation_id == correlation_id)
    if adapter_type:
        query = query.filter(Message.adapter_type == adapter_type)
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


@router.delete("/messages/{message_id}", response_model=SuccessResponse)
async def delete_message(
    message_id: int,
    db: Session = Depends(get_db),
) -> SuccessResponse:
    """
    Delete a message from the queue.

    Args:
        message_id: ID of message to delete
        db: Database session

    Returns:
        Success response

    Raises:
        HTTPException: If message not found
    """
    message = db.query(Message).filter(Message.id == message_id).first()
    if not message:
        raise HTTPException(status_code=404, detail="Message not found")

    db.delete(message)
    db.commit()

    return SuccessResponse(
        message="Message deleted successfully",
        data={"message_id": message_id},
    )


@router.post("/messages/cleanup", response_model=SuccessResponse)
async def cleanup_old_messages(
    db: Session = Depends(get_db),
) -> SuccessResponse:
    """
    Clean up old messages that have been retrieved.

    Deletes messages older than MESSAGE_RETENTION_HOURS that have been retrieved.

    Args:
        db: Database session

    Returns:
        Success response with count of deleted messages
    """
    cutoff_time = datetime.now(timezone.utc) - timedelta(
        hours=settings.message_retention_hours
    )

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
