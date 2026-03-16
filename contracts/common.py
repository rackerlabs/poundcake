"""Shared common contract models."""

from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Literal, Optional

from pydantic import Field

from contracts.base import ContractModel

JsonScalar = str | int | float | bool | None
JsonValue = JsonScalar | List[JsonScalar] | Dict[str, JsonScalar]


class ErrorItem(ContractModel):
    field: Optional[str] = None
    message: str


class ErrorEnvelope(ContractModel):
    code: str
    message: str
    details: List[ErrorItem] = Field(default_factory=list)
    request_id: Optional[str] = None


class SafeErrorDetail(ContractModel):
    message: str


class ProviderReference(ContractModel):
    provider_type: str = Field(..., min_length=1, max_length=100)
    reference_id: Optional[str] = Field(default=None, max_length=255)
    display_name: Optional[str] = Field(default=None, max_length=255)
    state: Optional[str] = Field(default=None, max_length=100)
    url: Optional[str] = Field(default=None, max_length=2048)


class SyncMetadata(ContractModel):
    operation_id: str = Field(..., min_length=1, max_length=255)
    synced_at: datetime


class ComponentHealth(ContractModel):
    status: Literal["healthy", "degraded", "unhealthy"]
    message: Optional[str] = None
    details: Optional[Dict[str, JsonValue]] = None
