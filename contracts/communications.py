"""Canonical communications contract models shared by PoundCake and Bakery."""

from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Literal, Optional

from pydantic import Field

from contracts.base import ContractModel
from contracts.common import JsonValue, ProviderReference, SafeErrorDetail, SyncMetadata


class CommunicationContext(ContractModel):
    labels: Dict[str, str] = Field(default_factory=dict)
    annotations: Dict[str, str] = Field(default_factory=dict)
    provider_type: Optional[str] = Field(default=None, max_length=100)
    execution_target: Optional[str] = Field(default=None, max_length=100)
    destination_target: Optional[str] = Field(default=None, max_length=255)
    provider_config: Dict[str, JsonValue] = Field(default_factory=dict)
    metadata: Dict[str, JsonValue] = Field(default_factory=dict)
    route_label: Optional[str] = Field(default=None, max_length=255)
    event_name: Optional[str] = Field(default=None, max_length=255)
    route_id: Optional[str] = Field(default=None, max_length=255)
    generator_url: Optional[str] = Field(default=None, max_length=2048)
    order_id: Optional[int] = None
    request_id: Optional[str] = Field(default=None, max_length=255)
    processing_status: Optional[str] = Field(default=None, max_length=100)
    alert_status: Optional[str] = Field(default=None, max_length=100)
    remediation_outcome: Optional[str] = Field(default=None, max_length=100)
    counter: Optional[int] = None
    clear_timeout_sec: Optional[int] = None
    clear_deadline_at: Optional[str] = Field(default=None, max_length=100)
    clear_timed_out_at: Optional[str] = Field(default=None, max_length=100)
    auto_close_eligible: Optional[bool] = None
    fingerprint: Optional[str] = Field(default=None, max_length=255)
    starts_at: Optional[str] = Field(default=None, max_length=100)
    ends_at: Optional[str] = Field(default=None, max_length=100)
    visibility: Optional[str] = Field(default=None, max_length=50)
    canonical: Dict[str, JsonValue] = Field(default_factory=dict)


class CommunicationCreateRequest(ContractModel):
    title: str = Field(..., min_length=1, max_length=512)
    description: str = Field(..., min_length=1)
    severity: Optional[str] = Field(default=None, max_length=50)
    category: Optional[str] = Field(default=None, max_length=100)
    source: Optional[str] = Field(default=None, max_length=100)
    context: CommunicationContext = Field(default_factory=CommunicationContext)


class CommunicationUpdateRequest(ContractModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=512)
    description: Optional[str] = Field(default=None, min_length=1)
    severity: Optional[str] = Field(default=None, max_length=50)
    category: Optional[str] = Field(default=None, max_length=100)
    state: Optional[str] = Field(default=None, max_length=50)
    context: CommunicationContext = Field(default_factory=CommunicationContext)


class CommunicationNotifyRequest(ContractModel):
    message: str = Field(..., min_length=1)
    visibility: Optional[str] = Field(default=None, max_length=50)
    context: CommunicationContext = Field(default_factory=CommunicationContext)


class CommunicationCloseRequest(ContractModel):
    resolution_code: Optional[str] = Field(default=None, max_length=100)
    resolution_notes: Optional[str] = Field(default=None, max_length=4096)
    state: str = Field(default="closed", max_length=50)
    context: CommunicationContext = Field(default_factory=CommunicationContext)


class CommunicationAcceptedResponse(ContractModel):
    communication_id: str = Field(..., min_length=1, max_length=255)
    operation_id: str = Field(..., min_length=1, max_length=255)
    action: str = Field(..., min_length=1, max_length=50)
    status: str = Field(..., min_length=1, max_length=50)
    created_at: datetime


class CommunicationMessageSummary(ContractModel):
    message: str
    visibility: Optional[str] = None
    created_at: datetime


class CommunicationSummary(ContractModel):
    title: Optional[str] = None
    description: Optional[str] = None
    severity: Optional[str] = None
    category: Optional[str] = None
    source: Optional[str] = None
    resolution_code: Optional[str] = None
    resolution_notes: Optional[str] = None
    messages: List[CommunicationMessageSummary] = Field(default_factory=list)
    provider_reference: Optional[ProviderReference] = None
    metadata: Dict[str, JsonValue] = Field(default_factory=dict)


class OperationResultSummary(ContractModel):
    success: Optional[bool] = None
    source: Optional[str] = None
    state: Optional[str] = None
    message: Optional[str] = None
    result_count: Optional[int] = None
    provider_reference: Optional[ProviderReference] = None


class CommunicationResponse(ContractModel):
    communication_id: str = Field(..., min_length=1, max_length=255)
    provider_type: str = Field(..., min_length=1, max_length=100)
    provider_reference: Optional[ProviderReference] = None
    state: str = Field(..., min_length=1, max_length=100)
    latest_error: Optional[SafeErrorDetail] = None
    created_at: datetime
    updated_at: datetime
    data_source: Literal["local_cache", "provider_sync", "dry_run"] = "local_cache"
    summary: Optional[CommunicationSummary] = None
    last_sync: Optional[SyncMetadata] = None


class CommunicationOperationResponse(ContractModel):
    operation_id: str = Field(..., min_length=1, max_length=255)
    communication_id: str = Field(..., min_length=1, max_length=255)
    action: str = Field(..., min_length=1, max_length=50)
    status: str = Field(..., min_length=1, max_length=50)
    attempt_count: int = Field(..., ge=0)
    max_attempts: int = Field(..., ge=0)
    next_attempt_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    last_error: Optional[SafeErrorDetail] = None
    result: Optional[OperationResultSummary] = None
    created_at: datetime
    updated_at: datetime


class CommunicationOperationListResponse(ContractModel):
    communication_id: str = Field(..., min_length=1, max_length=255)
    operations: List[CommunicationOperationResponse]
    count: int = Field(..., ge=0)
