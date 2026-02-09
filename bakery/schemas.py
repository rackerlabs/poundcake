#!/usr/bin/env python3
"""Pydantic schemas for Bakery API."""

from datetime import datetime
from typing import Optional, Dict, Any
from pydantic import BaseModel, Field


# Ticket Request Schemas
class TicketRequestBase(BaseModel):
    """Base schema for ticket requests."""

    correlation_id: str = Field(..., description="Unique request identifier")
    adapter_type: str = Field(
        ...,
        description="servicenow, jira, github, pagerduty, rackspace_core",
    )
    action: str = Field(..., description="create, update, close, comment, etc")
    request_data: Dict[str, Any] = Field(..., description="Adapter-specific payload")


class TicketRequestCreate(TicketRequestBase):
    """Schema for creating a ticket request."""

    pass


class TicketRequestResponse(TicketRequestBase):
    """Schema for ticket request response."""

    id: int
    ticket_id: Optional[str] = None
    status: str
    error_message: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    completed_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# Message Schemas
class MessageBase(BaseModel):
    """Base schema for messages."""

    correlation_id: str
    adapter_type: str
    status: str
    ticket_id: Optional[str] = None
    response_data: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None


class MessageResponse(MessageBase):
    """Schema for message response."""

    id: int
    created_at: datetime
    retrieved_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class MessageListResponse(BaseModel):
    """Schema for list of messages."""

    messages: list[MessageResponse]
    count: int


# Health Check Schemas
class ComponentHealth(BaseModel):
    """Health status of a single component."""

    status: str = Field(..., description="healthy, degraded, unhealthy")
    message: Optional[str] = None
    details: Optional[Dict[str, Any]] = None


class HealthResponse(BaseModel):
    """Health check response."""

    status: str = Field(..., description="Overall system health status")
    version: str = Field(..., description="Bakery version")
    instance_id: str = Field(..., description="Unique instance identifier")
    timestamp: datetime = Field(..., description="Health check timestamp")
    components: Dict[str, ComponentHealth] = Field(
        ..., description="Health status of individual components"
    )


# Generic Response Schemas
class ErrorResponse(BaseModel):
    """Standard error response."""

    error: str
    detail: Optional[str] = None
    correlation_id: Optional[str] = None


class SuccessResponse(BaseModel):
    """Standard success response."""

    message: str
    data: Optional[Dict[str, Any]] = None
