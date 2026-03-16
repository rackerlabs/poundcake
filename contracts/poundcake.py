"""Canonical PoundCake API contract models."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import Field

from contracts.base import ContractModel


class AppSettingsResponse(ContractModel):
    auth_enabled: bool
    prometheus_use_crds: bool
    prometheus_crd_namespace: str
    prometheus_url: str
    git_enabled: bool
    git_provider: Optional[str] = None
    stackstorm_enabled: bool
    version: str
    global_communications_configured: bool


class PrometheusRule(ContractModel):
    group: str
    name: str
    query: str
    crd: Optional[str] = None
    file: Optional[str] = None
    namespace: Optional[str] = None
    interval: Optional[str] = None
    duration: Optional[str] = None
    labels: Dict[str, str] = Field(default_factory=dict)
    annotations: Dict[str, str] = Field(default_factory=dict)
    state: Optional[str] = None
    health: Optional[str] = None


class PrometheusRuleListResponse(ContractModel):
    rules: List[PrometheusRule]
    source: str


class PrometheusRuleGroupListResponse(ContractModel):
    groups: List[Dict[str, Any]]


class MetricsListResponse(ContractModel):
    metrics: List[str]


class LabelListResponse(ContractModel):
    labels: List[str]


class LabelValuesResponse(ContractModel):
    label: str
    values: List[str]


class PrometheusHealthResponse(ContractModel):
    status: str
    details: Dict[str, Any] = Field(default_factory=dict)


class PrometheusMutationResponse(ContractModel):
    status: str
    message: Optional[str] = None
    details: Dict[str, Any] = Field(default_factory=dict)


class LivenessResponse(ContractModel):
    status: str
    version: str


class BulkUpsertResponse(ContractModel):
    created: int
    updated: int


class StackStormExecutionResponse(ContractModel):
    id: str
    status: Optional[str] = None
    action: Optional[str] = None
    context: Dict[str, Any] = Field(default_factory=dict)
    result: Dict[str, Any] = Field(default_factory=dict)
    parameters: Dict[str, Any] = Field(default_factory=dict)
    start_timestamp: Optional[str] = None
    end_timestamp: Optional[str] = None


class StackStormExecutionListResponse(ContractModel):
    executions: List[StackStormExecutionResponse]


class StackStormTaskListResponse(ContractModel):
    tasks: List[Dict[str, Any]]


class DeleteExecutionResponse(ContractModel):
    status: str
    execution_id: str


class StatusResponse(ContractModel):
    status: str
    message: Optional[str] = None


class SuppressionLifecycleResponse(ContractModel):
    status: str
    finalized: int


class WorkflowRegistrationRequest(ContractModel):
    pack: str
    name: str
    content: str


class WorkflowRegistrationResponse(ContractModel):
    workflow_id: str


class SyncCatalogStats(ContractModel):
    created: int = 0
    updated: int = 0
    skipped: int = 0
    processed: Optional[int] = None
    errors: int = 0


class SyncStackStormResponse(ContractModel):
    actions_created: int = 0
    actions_updated: int = 0
    workflows_created: int = 0
    workflows_updated: int = 0
    bootstrap_catalog: Dict[str, SyncCatalogStats] = Field(default_factory=dict)
    mark_bootstrap: bool = False
    completed_at: Optional[datetime] = None
