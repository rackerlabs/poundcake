#!/usr/bin/env python3
"""Pydantic schemas for Bakery API."""

from __future__ import annotations

from datetime import datetime
from typing import List

from pydantic import Field

from contracts.base import ContractModel
from contracts.common import ComponentHealth, ErrorEnvelope
from contracts.communications import (
    CommunicationAcceptedResponse,
    CommunicationCloseRequest,
    CommunicationContext,
    CommunicationCreateRequest,
    CommunicationNotifyRequest,
    CommunicationOperationListResponse,
    CommunicationOperationResponse,
    CommunicationResponse,
    CommunicationSummary,
    CommunicationUpdateRequest,
)

# Canonical contract exports
OperationAcceptedResponse = CommunicationAcceptedResponse
TicketContext = CommunicationContext
TicketCreateRequest = CommunicationCreateRequest
TicketUpdateRequest = CommunicationUpdateRequest
TicketCommentRequest = CommunicationNotifyRequest
TicketCloseRequest = CommunicationCloseRequest
TicketResponse = CommunicationResponse
TicketSummary = CommunicationSummary
TicketOperationResponse = CommunicationOperationResponse
TicketOperationListResponse = CommunicationOperationListResponse


class HealthResponse(ContractModel):
    """Health check response."""

    status: str = Field(..., description="Overall system health status")
    version: str = Field(..., description="Bakery version")
    instance_id: str = Field(..., description="Unique instance identifier")
    timestamp: datetime = Field(..., description="Health check timestamp")
    components: dict[str, ComponentHealth] = Field(
        ..., description="Health status of individual components"
    )


class ErrorResponse(ErrorEnvelope):
    """Standard error response."""


class MixerInfo(ContractModel):
    """Information about a single mixer."""

    mixer_type: str = Field(..., description="Mixer identifier")
    actions: List[str] = Field(..., description="Supported actions for this mixer")
    configured: bool = Field(
        ..., description="Whether credentials are configured (not necessarily valid)"
    )


class MixerListResponse(ContractModel):
    """Response for listing available mixers."""

    mixers: List[MixerInfo]
    count: int = Field(..., description="Number of registered mixers")


class MixerValidateResponse(ContractModel):
    """Response for mixer credential validation."""

    mixer_type: str = Field(..., description="Mixer that was validated")
    valid: bool = Field(..., description="Whether credentials are valid and connectivity works")
    message: str = Field(..., description="Human-readable validation result")
