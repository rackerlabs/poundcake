"""Shared Pydantic contract for PoundCake <-> Bakery communications."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class _BakeryContractModel(BaseModel):
    """Base model for owned Bakery communication contracts."""

    model_config = ConfigDict(extra="forbid")


class CommunicationOpenRequest(_BakeryContractModel):
    """Open a new logical communication."""

    title: str = Field(..., min_length=1, max_length=512)
    description: str = Field(..., min_length=1)
    message: str | None = Field(default=None, min_length=1)
    severity: str | None = Field(default=None, max_length=50)
    category: str | None = Field(default=None, max_length=100)
    source: str | None = Field(default=None, max_length=100)
    context: dict[str, Any] = Field(default_factory=dict)


class CommunicationUpdateRequest(_BakeryContractModel):
    """Update mutable communication fields."""

    title: str | None = Field(default=None, min_length=1, max_length=512)
    description: str | None = Field(default=None, min_length=1)
    severity: str | None = Field(default=None, max_length=50)
    category: str | None = Field(default=None, max_length=100)
    state: str | None = Field(default=None, max_length=50)
    context: dict[str, Any] = Field(default_factory=dict)


class CommunicationNotifyRequest(_BakeryContractModel):
    """Send a message/notification to an existing communication."""

    message: str | None = Field(default=None, min_length=1)
    comment: str | None = Field(default=None, min_length=1)
    visibility: str | None = Field(default=None, max_length=50)
    context: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _coalesce_message_and_comment(self) -> "CommunicationNotifyRequest":
        if self.message is None and self.comment is not None:
            self.message = self.comment
        if self.comment is None and self.message is not None:
            self.comment = self.message
        if self.message is None:
            raise ValueError("message is required")
        return self


class CommunicationCloseRequest(_BakeryContractModel):
    """Close a logical communication."""

    title: str | None = Field(default=None, min_length=1, max_length=512)
    description: str | None = Field(default=None, min_length=1)
    message: str | None = Field(default=None, min_length=1)
    source: str | None = Field(default=None, max_length=100)
    resolution_code: str | None = Field(default=None, max_length=100)
    resolution_notes: str | None = Field(default=None, max_length=4096)
    state: str | None = Field(default="closed", max_length=50)
    context: dict[str, Any] = Field(default_factory=dict)


class CommunicationAcceptedResponse(_BakeryContractModel):
    """Accepted async communication operation response."""

    communication_id: str
    operation_id: str
    action: str
    status: str
    created_at: datetime


class CommunicationResponse(_BakeryContractModel):
    """Logical communication status."""

    communication_id: str
    provider_type: str
    provider_reference_id: str | None = None
    state: str
    latest_error: str | None = None
    created_at: datetime
    updated_at: datetime
    data_source: str = "local_cache"
    communication_data: dict[str, Any] | None = None
    last_sync_operation_id: str | None = None
    last_sync_at: datetime | None = None


class CommunicationOperationResponse(_BakeryContractModel):
    """Detailed communication operation state."""

    operation_id: str
    communication_id: str
    action: str
    status: str
    attempt_count: int
    max_attempts: int
    next_attempt_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    last_error: str | None = None
    provider_response: dict[str, Any] | None = None
    created_at: datetime
    updated_at: datetime


class CommunicationOperationListResponse(_BakeryContractModel):
    """List of operations for a communication."""

    communication_id: str
    operations: list[CommunicationOperationResponse]
    count: int


class MonitorRouteCatalogEntry(_BakeryContractModel):
    """Normalized communication route entry registered by PoundCake."""

    scope: str = Field(..., min_length=1, max_length=32)
    owner_key: str = Field(..., min_length=1, max_length=255)
    route_id: str = Field(..., min_length=1, max_length=255)
    label: str = Field(..., min_length=1, max_length=255)
    execution_target: str = Field(..., min_length=1, max_length=100)
    destination_target: str = Field(default="", max_length=255)
    provider_config: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True
    outage_enabled: bool = False
    position: int = Field(default=1, ge=1)


class MonitorBootstrapCredentialResponse(_BakeryContractModel):
    """Bootstrap credential returned by Bakery admin APIs."""

    monitor_id: str
    key_id: str
    secret: str
    created_at: datetime


class MonitorRegistrationRequest(_BakeryContractModel):
    """Register or recover a PoundCake monitor identity."""

    monitor_id: str = Field(..., min_length=1, max_length=255)
    installation_id: str | None = Field(default=None, max_length=255)
    app_version: str | None = Field(default=None, max_length=100)


class MonitorRegistrationResponse(_BakeryContractModel):
    """Monitor credential response returned after successful registration."""

    monitor_uuid: str
    monitor_id: str
    hmac_key_id: str
    hmac_secret: str
    heartbeat_interval_sec: int
    miss_threshold: int
    route_sync_required: bool
    created_at: datetime


class MonitorRouteCatalogSyncRequest(_BakeryContractModel):
    """Full route catalog snapshot for one monitor."""

    catalog_hash: str = Field(..., min_length=1, max_length=64)
    routes: list[MonitorRouteCatalogEntry] = Field(default_factory=list)


class MonitorRouteCatalogSyncResponse(_BakeryContractModel):
    """Acknowledges a monitor route catalog sync."""

    monitor_uuid: str
    catalog_hash: str
    route_count: int
    updated_at: datetime


class MonitorHeartbeatRequest(_BakeryContractModel):
    """Liveness heartbeat sent by PoundCake."""

    catalog_hash: str | None = Field(default=None, max_length=64)
    installation_id: str | None = Field(default=None, max_length=255)
    app_version: str | None = Field(default=None, max_length=100)
    details: dict[str, Any] = Field(default_factory=dict)


class MonitorHeartbeatResponse(_BakeryContractModel):
    """Heartbeat acknowledgement and route sync hint."""

    monitor_uuid: str
    monitor_id: str
    status: str
    route_sync_required: bool
    heartbeat_interval_sec: int
    miss_threshold: int
    recorded_at: datetime
