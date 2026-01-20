"""Pydantic schemas for request/response validation."""

from datetime import datetime
from typing import Optional, Any, Dict, List
from pydantic import BaseModel, ConfigDict


# Alertmanager webhook schemas
class AlertLabels(BaseModel):
    """Alert labels from Alertmanager."""

    alertname: str
    severity: Optional[str] = None
    instance: Optional[str] = None

    model_config = ConfigDict(extra="allow")


class AlertAnnotations(BaseModel):
    """Alert annotations from Alertmanager."""

    summary: Optional[str] = None
    description: Optional[str] = None

    model_config = ConfigDict(extra="allow")


class AlertData(BaseModel):
    """Single alert from Alertmanager webhook."""

    status: str  # firing or resolved
    labels: AlertLabels
    annotations: Optional[AlertAnnotations] = None
    startsAt: datetime
    endsAt: Optional[datetime] = None
    generatorURL: Optional[str] = None
    fingerprint: str


class AlertmanagerWebhook(BaseModel):
    """Alertmanager webhook payload."""

    version: str
    groupKey: str
    truncatedAlerts: int = 0
    status: str
    receiver: str
    groupLabels: Dict[str, Any]
    commonLabels: Dict[str, Any]
    commonAnnotations: Dict[str, Any]
    externalURL: str
    alerts: List[AlertData]


# Response schemas
class WebhookResponse(BaseModel):
    """Response for webhook endpoint."""

    status: str
    request_id: str
    alerts_received: int
    task_ids: List[str]
    message: str


class AlertResponse(BaseModel):
    """Response for alert queries."""

    id: int
    fingerprint: str
    status: str
    alert_name: str
    severity: Optional[str]
    instance: Optional[str]
    labels: Dict[str, Any]
    processing_status: str
    task_id: Optional[str]
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class TaskStatusResponse(BaseModel):
    """Response for task status queries."""

    task_id: str
    status: str
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


class HealthResponse(BaseModel):
    """Health check response."""

    status: str
    version: str
    database: str
    redis: str
    celery: str
    timestamp: datetime


class StatsResponse(BaseModel):
    """Statistics response."""

    total_api_calls: int
    total_alerts: int
    alerts_by_status: Dict[str, int]
    alerts_by_processing_status: Dict[str, int]
    recent_alerts: int
