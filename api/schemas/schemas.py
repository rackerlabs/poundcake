#  ___                        _  ____      _
# |  _ \ ___  _   _ _ __   __| |/ ___|__ _| | _____
# | |_) / _ \| | | | '_ \ / _` | |   / _` | |/ / _ \
# |  __/ (_) | |_| | | | | (_| | |__| (_| |   <  __/
# |_|   \___/ \__,_|_| |_|\__,_|\____\__,_|_|\_\___|
#
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
    req_id: str
    fingerprint: str
    alert_status: str  # firing or resolved (from Alertmanager)
    processing_status: str  # new, processing, complete, failed (internal)
    alert_name: str
    group_name: Optional[str]  # From groupLabels, used for recipe matching
    severity: Optional[str]
    instance: Optional[str]
    prometheus: Optional[str]
    labels: Dict[str, Any]
    counter: int
    ticket_number: Optional[str]
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class HealthResponse(BaseModel):
    """Health check response."""

    status: str
    version: str
    database: str
    stackstorm: str
    timestamp: datetime


class StatsResponse(BaseModel):
    """Statistics response."""

    total_alerts: int
    total_recipes: int
    total_executions: int
    alerts_by_processing_status: Dict[str, int]  # new, processing, complete, failed
    alerts_by_alert_status: Dict[str, int]  # firing, resolved
    executions_by_status: Dict[str, int]  # new, processing, complete
    recent_alerts: int
