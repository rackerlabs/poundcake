#!/usr/bin/env python3
"""Pydantic schemas for Bakery API."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class TicketCreateRequest(BaseModel):
    """Create a new logical ticket."""

    title: str = Field(..., min_length=1, max_length=512)
    description: str = Field(..., min_length=1)
    severity: Optional[str] = Field(default=None, max_length=50)
    category: Optional[str] = Field(default=None, max_length=100)
    source: Optional[str] = Field(default=None, max_length=100)
    context: Dict[str, Any] = Field(default_factory=dict)


class TicketUpdateRequest(BaseModel):
    """Update mutable ticket fields."""

    title: Optional[str] = Field(default=None, min_length=1, max_length=512)
    description: Optional[str] = Field(default=None, min_length=1)
    severity: Optional[str] = Field(default=None, max_length=50)
    category: Optional[str] = Field(default=None, max_length=100)
    state: Optional[str] = Field(default=None, max_length=50)
    context: Dict[str, Any] = Field(default_factory=dict)


class TicketCommentRequest(BaseModel):
    """Add a comment to a ticket."""

    comment: str = Field(..., min_length=1)
    visibility: Optional[str] = Field(default=None, max_length=50)
    context: Dict[str, Any] = Field(default_factory=dict)


class TicketCloseRequest(BaseModel):
    """Close a ticket."""

    resolution_code: Optional[str] = Field(default=None, max_length=100)
    resolution_notes: Optional[str] = Field(default=None, max_length=4096)
    state: Optional[str] = Field(default="closed", max_length=50)
    context: Dict[str, Any] = Field(default_factory=dict)


class OperationAcceptedResponse(BaseModel):
    """Accepted async operation response."""

    ticket_id: str
    operation_id: str
    action: str
    status: str
    created_at: datetime


class TicketResponse(BaseModel):
    """Logical ticket status."""

    ticket_id: str
    provider_type: str
    provider_ticket_id: Optional[str] = None
    state: str
    latest_error: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    data_source: str = "local_cache"
    ticket_data: Optional[Dict[str, Any]] = None
    last_sync_operation_id: Optional[str] = None
    last_sync_at: Optional[datetime] = None


class TicketOperationResponse(BaseModel):
    """Detailed ticket operation state."""

    operation_id: str
    ticket_id: str
    action: str
    status: str
    attempt_count: int
    max_attempts: int
    next_attempt_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    last_error: Optional[str] = None
    provider_response: Optional[Dict[str, Any]] = None
    created_at: datetime
    updated_at: datetime


class TicketOperationListResponse(BaseModel):
    """List of operations for a ticket."""

    ticket_id: str
    operations: List[TicketOperationResponse]
    count: int


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


class ErrorResponse(BaseModel):
    """Standard error response."""

    error: str
    detail: Optional[str] = None


class MixerInfo(BaseModel):
    """Information about a single mixer."""

    mixer_type: str = Field(..., description="Mixer identifier")
    actions: List[str] = Field(..., description="Supported actions for this mixer")
    configured: bool = Field(
        ..., description="Whether credentials are configured (not necessarily valid)"
    )


class MixerListResponse(BaseModel):
    """Response for listing available mixers."""

    mixers: List[MixerInfo]
    count: int = Field(..., description="Number of registered mixers")


class MixerValidateResponse(BaseModel):
    """Response for mixer credential validation."""

    mixer_type: str = Field(..., description="Mixer that was validated")
    valid: bool = Field(..., description="Whether credentials are valid and connectivity works")
    message: str = Field(..., description="Human-readable validation result")
