#  ___                        _  ____      _
# |  _ \ ___  _   _ _ __   __| |/ ___|__ _| | _____
# | |_) / _ \| | | | '_ \ / _` | |   / _` | |/ / _ \
# |  __/ (_) | |_| | | | | (_| | |__| (_| |   <  __/
# |_|   \___/ \__,_|_| |_|\__,_|\____\__,_|_|\_\___|
#
"""Pydantic schemas for PoundCake API."""

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from typing import List, Optional, Dict, Any
from datetime import datetime

from api.types import (
    AuthBindingType,
    AuthPrincipalType,
    AuthProvider,
    AuthRole,
    DishProcessingStatus,
    OrderProcessingStatus,
    AlertStatus,
    CanonicalExecutionStatus,
    OnSuccessAction,
    OnFailureAction,
    SuppressionScope,
    SuppressionStatus,
    SuppressionMatcherOperator,
    RunPhase,
    DishRunPhase,
    RunCondition,
    ExecutionPurpose,
    RemediationOutcome,
)
from api.services.communications import (
    ALERTMANAGER_REQUIRED_ANNOTATION_FIELDS,
    ALERTMANAGER_REQUIRED_LABEL_FIELDS,
    normalize_destination_type,
    normalize_route_provider_config,
)

# =============================================================================
# Health & Stats
# =============================================================================


class ComponentHealth(BaseModel):
    status: str  # healthy, degraded, unhealthy
    message: Optional[str] = None
    details: Optional[Dict[str, Any]] = None


class HealthResponse(BaseModel):
    status: str  # overall: healthy, degraded, unhealthy
    version: str
    instance_id: str
    timestamp: datetime
    components: Dict[str, ComponentHealth]  # database, stackstorm, mongodb, rabbitmq, redis


class StatsResponse(BaseModel):
    total_alerts: int
    total_recipes: int
    total_executions: int
    alerts_by_processing_status: Dict[str, int]
    alerts_by_alert_status: Dict[str, int]
    executions_by_status: Dict[str, int]
    recent_alerts: int


class CommunicationRouteBase(BaseModel):
    id: Optional[str] = None
    label: str = Field(..., min_length=1, max_length=255)
    execution_target: str = Field(..., min_length=1, max_length=100)
    destination_target: Optional[str] = Field(default="", max_length=255)
    provider_config: Dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True
    position: int = Field(default=1, ge=1)

    @field_validator("execution_target")
    @classmethod
    def _validate_execution_target(cls, value: str) -> str:
        normalized = normalize_destination_type(value)
        if not normalized:
            raise ValueError("execution_target is required")
        return normalized


class CommunicationRouteCreate(CommunicationRouteBase):
    @model_validator(mode="after")
    def _normalize_provider_config(self) -> "CommunicationRouteCreate":
        self.provider_config = normalize_route_provider_config(
            self.execution_target,
            self.provider_config,
        )
        return self


class CommunicationRouteResponse(CommunicationRouteBase):
    id: str

    @model_validator(mode="after")
    def _normalize_provider_config(self) -> "CommunicationRouteResponse":
        self.provider_config = normalize_route_provider_config(
            self.execution_target,
            self.provider_config,
            require_required=False,
        )
        return self


class CommunicationPolicyUpdate(BaseModel):
    routes: List[CommunicationRouteCreate] = Field(default_factory=list)


class CommunicationPolicyResponse(BaseModel):
    configured: bool
    routes: List[CommunicationRouteResponse] = Field(default_factory=list)
    lifecycle_summary: Dict[str, str] = Field(default_factory=dict)


class RecipeCommunicationsConfig(BaseModel):
    mode: str = Field(default="inherit")
    routes: List[CommunicationRouteCreate] = Field(default_factory=list)

    @field_validator("mode")
    @classmethod
    def _validate_mode(cls, value: str) -> str:
        normalized = (value or "").strip().lower()
        if normalized not in {"inherit", "local"}:
            raise ValueError("communications.mode must be either 'inherit' or 'local'")
        return normalized


class RecipeCommunicationsResponse(BaseModel):
    mode: str
    effective_source: Optional[str] = None
    routes: List[CommunicationRouteResponse] = Field(default_factory=list)


class AlertmanagerAlertRequest(BaseModel):
    status: str = Field(..., min_length=1)
    labels: Dict[str, Any] = Field(default_factory=dict)
    annotations: Dict[str, Any] = Field(default_factory=dict)
    startsAt: str = Field(..., min_length=1)
    fingerprint: str = Field(..., min_length=1)
    endsAt: Optional[Any] = None
    generatorURL: Optional[str] = None

    model_config = ConfigDict(extra="allow")

    @field_validator("labels")
    @classmethod
    def _validate_labels(cls, value: Dict[str, Any]) -> Dict[str, Any]:
        missing = sorted(
            field
            for field in ALERTMANAGER_REQUIRED_LABEL_FIELDS
            if not str(value.get(field) or "").strip()
        )
        if missing:
            raise ValueError(f"labels missing required fields: {', '.join(missing)}")
        return value

    @field_validator("annotations")
    @classmethod
    def _validate_annotations(cls, value: Dict[str, Any]) -> Dict[str, Any]:
        missing = sorted(
            field
            for field in ALERTMANAGER_REQUIRED_ANNOTATION_FIELDS
            if not str(value.get(field) or "").strip()
        )
        if missing:
            raise ValueError(f"annotations missing required fields: {', '.join(missing)}")
        return value


class AlertmanagerWebhookRequest(BaseModel):
    status: str = Field(..., min_length=1)
    alerts: List[AlertmanagerAlertRequest] = Field(..., min_length=1)
    receiver: Optional[str] = None
    groupKey: Optional[str] = None
    groupLabels: Dict[str, Any] = Field(default_factory=dict)
    commonLabels: Dict[str, Any] = Field(default_factory=dict)
    commonAnnotations: Dict[str, Any] = Field(default_factory=dict)
    externalURL: Optional[str] = None
    version: Optional[str] = None
    truncatedAlerts: Optional[int] = None

    model_config = ConfigDict(extra="allow")


# =============================================================================
# Ingredient Schemas (Global)
# =============================================================================


class IngredientBase(BaseModel):
    """Base schema for Ingredient creation/updates."""

    execution_target: str = Field(..., max_length=100)
    destination_target: Optional[str] = Field(default="", max_length=255)
    task_key_template: str = Field(..., max_length=255)

    execution_id: Optional[str] = Field(None, max_length=100)
    action_id: Optional[str] = Field(
        None, max_length=100, description="Deprecated alias for execution_id"
    )
    execution_payload: Optional[Dict[str, Any]] = None
    execution_parameters: Optional[Dict[str, Any]] = None

    execution_engine: str = Field(default="undefined", max_length=50)
    execution_purpose: ExecutionPurpose = Field(default="utility")
    ingredient_kind: Optional[ExecutionPurpose] = Field(
        None, description="Deprecated alias for execution_purpose"
    )
    is_default: bool = False
    is_blocking: bool = True
    expected_duration_sec: int = Field(..., gt=0)
    timeout_duration_sec: int = Field(default=300, gt=0)
    retry_count: int = Field(default=0, ge=0)
    retry_delay: int = Field(default=5, ge=0)
    on_failure: OnFailureAction = Field(default="stop")

    @field_validator("execution_payload")
    @classmethod
    def _validate_execution_payload(
        cls, value: Optional[Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        if value is None:
            return value
        if not isinstance(value, dict):
            raise ValueError("execution_payload must be an object when provided")
        return value

    @field_validator("execution_engine")
    @classmethod
    def _validate_execution_engine(cls, value: str) -> str:
        normalized = (value or "").strip().lower()
        if normalized not in {"undefined", "stackstorm", "bakery", "native", "argocd"}:
            raise ValueError(
                "execution_engine must be one of: undefined, stackstorm, bakery, native, argocd"
            )
        return normalized

    @model_validator(mode="after")
    def _coalesce_deprecated_aliases(self) -> "IngredientBase":
        if self.execution_id is None and self.action_id is not None:
            self.execution_id = self.action_id
        if self.action_id is None and self.execution_id is not None:
            self.action_id = self.execution_id
        if self.ingredient_kind is not None:
            self.execution_purpose = self.ingredient_kind
        self.ingredient_kind = self.execution_purpose
        return self


class IngredientCreate(IngredientBase):
    """Schema for creating a new global ingredient."""

    pass


class IngredientUpdate(BaseModel):
    """Schema for updating an ingredient (all fields optional)."""

    execution_target: Optional[str] = Field(None, max_length=100)
    destination_target: Optional[str] = Field(None, max_length=255)
    task_key_template: Optional[str] = Field(None, max_length=255)
    execution_id: Optional[str] = Field(None, max_length=100)
    action_id: Optional[str] = Field(
        None, max_length=100, description="Deprecated alias for execution_id"
    )
    execution_payload: Optional[Dict[str, Any]] = None
    execution_parameters: Optional[Dict[str, Any]] = None
    execution_engine: Optional[str] = Field(None, max_length=50)
    execution_purpose: Optional[ExecutionPurpose] = None
    ingredient_kind: Optional[ExecutionPurpose] = Field(
        None, description="Deprecated alias for execution_purpose"
    )
    is_default: Optional[bool] = None
    is_blocking: Optional[bool] = None
    expected_duration_sec: Optional[int] = Field(None, gt=0)
    timeout_duration_sec: Optional[int] = Field(None, gt=0)
    retry_count: Optional[int] = Field(None, ge=0)
    retry_delay: Optional[int] = Field(None, ge=0)
    on_failure: Optional[OnFailureAction] = None

    @field_validator("execution_payload")
    @classmethod
    def _validate_execution_payload(
        cls, value: Optional[Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        if value is None:
            return value
        if not isinstance(value, dict):
            raise ValueError("execution_payload must be an object when provided")
        return value

    @field_validator("execution_engine")
    @classmethod
    def _validate_execution_engine(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        normalized = value.strip().lower()
        if normalized not in {"undefined", "stackstorm", "bakery", "native", "argocd"}:
            raise ValueError(
                "execution_engine must be one of: undefined, stackstorm, bakery, native, argocd"
            )
        return normalized

    @model_validator(mode="after")
    def _coalesce_deprecated_aliases(self) -> "IngredientUpdate":
        if self.execution_id is None and self.action_id is not None:
            self.execution_id = self.action_id
        if self.action_id is None and self.execution_id is not None:
            self.action_id = self.execution_id
        if self.execution_purpose is None and self.ingredient_kind is not None:
            self.execution_purpose = self.ingredient_kind
        if self.ingredient_kind is None and self.execution_purpose is not None:
            self.ingredient_kind = self.execution_purpose
        return self


class IngredientResponse(IngredientBase):
    """Schema for ingredient responses (includes DB fields)."""

    id: int
    created_at: datetime
    updated_at: datetime
    deleted: bool
    deleted_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


# =============================================================================
# RecipeIngredient Schemas (Junction)
# =============================================================================


class RecipeIngredientBase(BaseModel):
    ingredient_id: int = Field(..., ge=1)
    step_order: int = Field(..., ge=1)
    on_success: OnSuccessAction = Field(default="continue")
    parallel_group: int = Field(default=0, ge=0)
    depth: int = Field(default=0, ge=0)
    execution_parameters_override: Optional[Dict[str, Any]] = None
    run_phase: RunPhase = Field(default="both")
    run_condition: RunCondition = Field(default="always")


class RecipeIngredientCreate(RecipeIngredientBase):
    pass


class RecipeIngredientResponse(RecipeIngredientBase):
    id: int
    recipe_id: int
    ingredient: Optional[IngredientResponse] = None

    model_config = ConfigDict(from_attributes=True)


# =============================================================================
# Recipe Schemas
# =============================================================================


class RecipeBase(BaseModel):
    """Base schema for Recipe creation/updates."""

    name: str = Field(..., max_length=255)
    description: Optional[str] = None
    enabled: bool = True
    clear_timeout_sec: Optional[int] = Field(default=None, gt=0)


class RecipeCreate(RecipeBase):
    """Schema for creating a recipe with recipe_ingredients."""

    recipe_ingredients: List[RecipeIngredientCreate] = Field(..., min_length=1)
    communications: RecipeCommunicationsConfig = Field(default_factory=RecipeCommunicationsConfig)


class RecipeUpdate(BaseModel):
    """Schema for updating a recipe (all fields optional)."""

    name: Optional[str] = Field(None, max_length=255)
    description: Optional[str] = None
    enabled: Optional[bool] = None
    clear_timeout_sec: Optional[int] = Field(default=None, gt=0)
    recipe_ingredients: Optional[List[RecipeIngredientCreate]] = Field(default=None, min_length=1)
    communications: Optional[RecipeCommunicationsConfig] = None


class RecipeResponse(RecipeBase):
    """Schema for recipe responses (includes DB fields)."""

    id: int
    created_at: datetime
    updated_at: datetime
    deleted: bool
    deleted_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class RecipeDetailResponse(RecipeResponse):
    """Schema for detailed recipe responses (includes recipe_ingredients)."""

    recipe_ingredients: List[RecipeIngredientResponse] = []
    communications: RecipeCommunicationsResponse = Field(
        default_factory=lambda: RecipeCommunicationsResponse(mode="inherit")
    )


# =============================================================================
# Dish Schemas
# =============================================================================


class DishBase(BaseModel):
    """Base schema for Dish."""

    req_id: str = Field(..., max_length=100)
    processing_status: DishProcessingStatus = Field(default="new")
    run_phase: DishRunPhase = Field(default="firing")


class DishUpdate(BaseModel):
    """Schema for updating a dish."""

    processing_status: Optional[DishProcessingStatus] = None
    execution_status: Optional[str] = Field(None, max_length=50)
    execution_ref: Optional[str] = Field(None, max_length=100)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    expected_duration_sec: Optional[int] = None
    actual_duration_sec: Optional[int] = None
    result: Optional[Any] = None
    error_message: Optional[str] = None
    retry_attempt: Optional[int] = None
    run_phase: Optional[DishRunPhase] = None


class DishResponse(DishBase):
    """Schema for dish responses."""

    id: int
    order_id: Optional[int] = None
    recipe_id: int
    execution_ref: Optional[str] = None
    execution_status: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    expected_duration_sec: Optional[int] = None
    actual_duration_sec: Optional[int] = None
    result: Optional[Any] = None
    error_message: Optional[str] = None
    retry_attempt: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class DishDetailResponse(DishResponse):
    """Schema for detailed dish responses (includes recipe)."""

    recipe: Optional[RecipeDetailResponse] = None


# =============================================================================
# Order Schemas
# =============================================================================


class OrderBase(BaseModel):
    """Base schema for Order."""

    req_id: str = Field(..., max_length=100)
    fingerprint: str = Field(..., max_length=255)
    alert_status: str = Field(..., max_length=50)
    alert_group_name: str = Field(..., max_length=255)
    labels: Dict[str, Any]
    starts_at: datetime
    bakery_ticket_id: Optional[str] = Field(None, max_length=36)
    bakery_operation_id: Optional[str] = Field(None, max_length=36)
    bakery_ticket_state: Optional[str] = Field(None, max_length=32)
    bakery_permanent_failure: bool = False
    bakery_last_error: Optional[str] = None
    bakery_comms_id: Optional[str] = Field(None, max_length=36)
    fingerprint_when_active: Optional[str] = Field(None, max_length=255)
    remediation_outcome: RemediationOutcome = "pending"
    clear_timeout_sec: Optional[int] = Field(default=None, ge=1)
    clear_deadline_at: Optional[datetime] = None
    clear_timed_out_at: Optional[datetime] = None
    auto_close_eligible: bool = False


class OrderCreate(OrderBase):
    """Schema for creating an order."""

    processing_status: OrderProcessingStatus = Field(default="new")
    is_active: bool = True
    severity: Optional[str] = Field(None, max_length=50)
    instance: Optional[str] = Field(None, max_length=255)
    counter: int = 1
    annotations: Optional[Dict[str, Any]] = None
    raw_data: Optional[Dict[str, Any]] = None
    ends_at: Optional[datetime] = None


class OrderUpdate(BaseModel):
    """Schema for updating an order (all fields optional)."""

    alert_status: Optional[AlertStatus] = None
    processing_status: Optional[OrderProcessingStatus] = None
    is_active: Optional[bool] = None
    ends_at: Optional[datetime] = None
    bakery_comms_id: Optional[str] = Field(None, max_length=36)
    bakery_ticket_state: Optional[str] = Field(None, max_length=32)
    bakery_permanent_failure: Optional[bool] = None
    bakery_last_error: Optional[str] = None
    fingerprint_when_active: Optional[str] = Field(None, max_length=255)
    remediation_outcome: Optional[RemediationOutcome] = None
    clear_timeout_sec: Optional[int] = Field(default=None, ge=1)
    clear_deadline_at: Optional[datetime] = None
    clear_timed_out_at: Optional[datetime] = None
    auto_close_eligible: Optional[bool] = None


class OrderResponse(OrderBase):
    """Schema for order responses."""

    id: int
    processing_status: OrderProcessingStatus
    is_active: bool
    severity: Optional[str] = None
    instance: Optional[str] = None
    counter: int
    annotations: Optional[Dict[str, Any]] = None
    raw_data: Optional[Dict[str, Any]] = None
    ends_at: Optional[datetime] = None
    communications: List["OrderCommunicationResponse"] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class DishIngredientUpsert(BaseModel):
    """Upsert payload for dish ingredient execution results."""

    recipe_ingredient_id: Optional[int] = None
    execution_ref: Optional[str] = None
    task_key: Optional[str] = None
    execution_engine: Optional[str] = None
    execution_target: Optional[str] = None
    destination_target: Optional[str] = None
    execution_payload: Optional[Dict[str, Any]] = None
    execution_parameters: Optional[Dict[str, Any]] = None
    execution_status: Optional[str] = None
    attempt: Optional[int] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    canceled_at: Optional[datetime] = None
    result: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class DishIngredientBulkUpsert(BaseModel):
    """Bulk upsert payload for dish ingredient executions."""

    items: List[DishIngredientUpsert]

    model_config = ConfigDict(from_attributes=True)


class DishIngredientResponse(BaseModel):
    """Dish ingredient execution record."""

    id: int
    dish_id: int
    recipe_ingredient_id: Optional[int] = None
    task_key: Optional[str] = None
    execution_engine: Optional[str] = None
    execution_target: Optional[str] = None
    destination_target: Optional[str] = None
    execution_ref: Optional[str] = None
    execution_payload: Optional[Dict[str, Any]] = None
    execution_parameters: Optional[Dict[str, Any]] = None
    execution_status: Optional[str] = None
    attempt: int
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    canceled_at: Optional[datetime] = None
    result: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None
    deleted: bool
    deleted_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class OrderDetailResponse(OrderResponse):
    """Schema for detailed order responses (includes dishes)."""

    dishes: List[DishResponse] = []


class OrderCommunicationBase(BaseModel):
    execution_target: str = Field(..., max_length=100)
    destination_target: str = Field(default="", max_length=255)
    bakery_ticket_id: Optional[str] = Field(default=None, max_length=36)
    bakery_operation_id: Optional[str] = Field(default=None, max_length=36)
    lifecycle_state: str = Field(default="pending", max_length=32)
    remote_state: Optional[str] = Field(default=None, max_length=64)
    writable: bool = True
    reopenable: bool = False
    last_error: Optional[str] = None


class OrderCommunicationResponse(OrderCommunicationBase):
    id: int
    order_id: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class IncidentTimelineEvent(BaseModel):
    timestamp: Optional[datetime] = None
    event_type: str
    status: str
    title: str
    details: Dict[str, Any] = Field(default_factory=dict)
    correlation_ids: Dict[str, str] = Field(default_factory=dict)


class IncidentTimelineResponse(BaseModel):
    order: OrderResponse
    events: List[IncidentTimelineEvent]


# ============================================================================
# Suppression Models
# ============================================================================


class SuppressionMatcher(BaseModel):
    label_key: str = Field(..., min_length=1, max_length=255)
    operator: SuppressionMatcherOperator
    value: Optional[str] = None


class SuppressionCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    starts_at: datetime
    ends_at: datetime
    scope: SuppressionScope = "matchers"
    matchers: List[SuppressionMatcher] = Field(default_factory=list)
    reason: Optional[str] = None
    created_by: Optional[str] = Field(default=None, max_length=255)
    summary_ticket_enabled: bool = True
    enabled: bool = True


class SuppressionUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    ends_at: Optional[datetime] = None
    reason: Optional[str] = None
    enabled: Optional[bool] = None
    matchers: Optional[List[SuppressionMatcher]] = None


class SuppressionResponse(BaseModel):
    id: int
    name: str
    reason: Optional[str] = None
    scope: SuppressionScope
    status: SuppressionStatus
    enabled: bool
    starts_at: datetime
    ends_at: datetime
    canceled_at: Optional[datetime] = None
    created_by: Optional[str] = None
    summary_ticket_enabled: bool
    created_at: datetime
    updated_at: datetime
    matchers: List[SuppressionMatcher] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class SuppressionStatsResponse(BaseModel):
    suppression_id: int
    total_suppressed: int
    by_alertname: Dict[str, int]
    by_severity: Dict[str, int]
    first_seen_at: Optional[datetime] = None
    last_seen_at: Optional[datetime] = None


class SuppressedActivityResponse(BaseModel):
    id: int
    suppression_id: int
    received_at: datetime
    fingerprint: Optional[str] = None
    alertname: Optional[str] = None
    severity: Optional[str] = None
    status: str
    req_id: Optional[str] = None
    labels_json: Dict[str, Any]
    annotations_json: Optional[Dict[str, Any]] = None

    model_config = ConfigDict(from_attributes=True)


class SuppressionSummaryResponse(BaseModel):
    state: str
    total_suppressed: int
    total_cleared: int = 0
    total_still_firing: int = 0
    by_alertname_json: Optional[Dict[str, Any]] = None
    by_severity_json: Optional[Dict[str, Any]] = None
    still_firing_alerts_json: Optional[Dict[str, Any]] = None
    first_seen_at: Optional[datetime] = None
    last_seen_at: Optional[datetime] = None
    bakery_ticket_id: Optional[str] = None
    bakery_create_operation_id: Optional[str] = None
    bakery_close_operation_id: Optional[str] = None
    summary_created_at: Optional[datetime] = None
    summary_close_at: Optional[datetime] = None
    last_error: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class SuppressionDetailResponse(SuppressionResponse):
    summary: Optional[SuppressionSummaryResponse] = None
    counters: SuppressionStatsResponse


class ObservabilityOverviewResponse(BaseModel):
    health: Dict[str, Any]
    queue: Dict[str, int]
    failures: Dict[str, Any]
    bakery: Dict[str, Any]
    suppressions: Dict[str, Any]


class ObservabilityActivityRecord(BaseModel):
    type: str
    status: str
    title: str
    summary: Optional[str] = None
    timestamp: Optional[datetime] = None
    target_kind: str
    target_id: str
    link_hint: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class CommunicationActivityRecord(BaseModel):
    communication_id: str
    reference_type: str
    reference_id: str
    reference_name: Optional[str] = None
    channel: str
    destination: Optional[str] = None
    ticket_id: Optional[str] = None
    provider_reference_id: Optional[str] = None
    operation_id: Optional[str] = None
    lifecycle_state: Optional[str] = None
    remote_state: Optional[str] = None
    last_error: Optional[str] = None
    writable: Optional[bool] = None
    reopenable: Optional[bool] = None
    updated_at: Optional[datetime] = None


class BakeryOperationRecord(BaseModel):
    source: str
    reference_id: str
    reference_type: Optional[str] = None
    reference_name: Optional[str] = None
    channel: Optional[str] = None
    destination: Optional[str] = None
    ticket_id: Optional[str] = None
    provider_reference_id: Optional[str] = None
    operation_id: Optional[str] = None
    status: Optional[str] = None
    execution_target: Optional[str] = None
    destination_target: Optional[str] = None
    remote_state: Optional[str] = None
    writable: Optional[bool] = None
    reopenable: Optional[bool] = None
    last_error: Optional[str] = None
    updated_at: Optional[datetime] = None
    details: Optional[Dict[str, Any]] = None


# ============================================================================
# Operation Response Models
# ============================================================================


class WebhookResponse(BaseModel):
    """Response from webhook endpoint."""

    status: str  # created, counter_incremented, resolved, ignored, no_alerts
    order_id: Optional[int] = None
    message: Optional[str] = None
    results: Optional[List[Dict[str, Any]]] = None

    model_config = ConfigDict(from_attributes=True)


class OrderDispatchResponse(BaseModel):
    """Response from order dispatch endpoint."""

    status: str  # dispatched, skipped
    order_id: int
    dish_id: Optional[int] = None
    run_phase: Optional[DishRunPhase] = None
    recipe_id: Optional[int] = None
    recipe_name: Optional[str] = None
    reason: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class ExecuteRequest(BaseModel):
    execution_engine: str = Field(..., max_length=50)
    execution_target: str = Field(..., max_length=255)
    execution_payload: Optional[Dict[str, Any]] = None
    execution_parameters: Optional[Dict[str, Any]] = None
    retry_count: int = Field(default=0, ge=0)
    retry_delay: int = Field(default=0, ge=0)
    timeout_duration_sec: int = Field(default=300, gt=0)
    context: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("execution_engine")
    @classmethod
    def _validate_execution_engine(cls, value: str) -> str:
        normalized = (value or "").strip().lower()
        if normalized not in {"stackstorm", "bakery"}:
            raise ValueError("execution_engine must be one of: stackstorm, bakery")
        return normalized

    @field_validator("execution_payload", "execution_parameters")
    @classmethod
    def _validate_object_fields(cls, value: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if value is None:
            return value
        if not isinstance(value, dict):
            raise ValueError("value must be an object when provided")
        return value


class ExecutionEnvelopeResponse(BaseModel):
    execution_ref: Optional[str] = None
    engine: str
    status: CanonicalExecutionStatus
    error_message: Optional[str] = None
    result: Optional[Dict[str, Any]] = None
    raw: Optional[Dict[str, Any]] = None
    attempts: int = 1

    model_config = ConfigDict(from_attributes=True)


class SessionResponse(BaseModel):
    """Response from login endpoint."""

    session_id: str
    username: str
    expires_at: str  # ISO format datetime
    provider: AuthProvider
    role: AuthRole
    display_name: Optional[str] = None
    is_superuser: bool = False
    permissions: List[str] = Field(default_factory=list)
    token_type: str = "Bearer"

    model_config = ConfigDict(from_attributes=True)


class AuthLoginRequest(BaseModel):
    """Password login request."""

    provider: Optional[AuthProvider] = None
    username: str = Field(..., min_length=1, max_length=255)
    password: str = Field(..., min_length=1, max_length=255)


class AuthProviderResponse(BaseModel):
    """Enabled auth provider metadata for UI and CLI discovery."""

    name: AuthProvider
    label: str
    login_mode: str
    cli_login_mode: str
    browser_login: bool = False
    device_login: bool = False
    password_login: bool = False


class AuthMeResponse(BaseModel):
    """Current authenticated principal metadata."""

    username: str
    display_name: Optional[str] = None
    provider: AuthProvider
    role: AuthRole
    principal_type: AuthPrincipalType
    principal_id: Optional[int] = None
    is_superuser: bool = False
    permissions: List[str] = Field(default_factory=list)
    groups: List[str] = Field(default_factory=list)
    expires_at: Optional[str] = None


class DeviceAuthorizationStartResponse(BaseModel):
    """Auth0 device login start payload."""

    provider: AuthProvider = "auth0"
    device_code: str
    user_code: str
    verification_uri: str
    verification_uri_complete: Optional[str] = None
    expires_in: int
    interval: int


class DeviceAuthorizationPollRequest(BaseModel):
    """Auth0 device authorization poll request."""

    provider: AuthProvider = "auth0"
    device_code: str = Field(..., min_length=1)


class DeviceAuthorizationPollResponse(BaseModel):
    """Auth0 device authorization status response."""

    status: str
    interval: Optional[int] = None
    detail: Optional[str] = None
    session: Optional[SessionResponse] = None


class AuthPrincipalResponse(BaseModel):
    """Observed principal metadata for access management."""

    id: int
    provider: AuthProvider
    subject_id: str
    username: str
    display_name: Optional[str] = None
    principal_type: AuthPrincipalType
    groups: List[str] = Field(default_factory=list)
    last_seen_at: datetime
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AuthRoleBindingCreate(BaseModel):
    """Create a new RBAC binding."""

    provider: AuthProvider
    binding_type: AuthBindingType
    role: AuthRole
    principal_id: Optional[int] = None
    external_group: Optional[str] = Field(default=None, max_length=255)
    created_by: Optional[str] = Field(default=None, max_length=255)

    @model_validator(mode="after")
    def _validate_target(self) -> "AuthRoleBindingCreate":
        if self.binding_type == "user" and self.principal_id is None:
            raise ValueError("principal_id is required for user bindings")
        if self.binding_type == "group" and not str(self.external_group or "").strip():
            raise ValueError("external_group is required for group bindings")
        return self


class AuthRoleBindingUpdate(BaseModel):
    """Update an existing RBAC binding."""

    role: Optional[AuthRole] = None
    external_group: Optional[str] = Field(default=None, max_length=255)


class AuthRoleBindingResponse(BaseModel):
    """RBAC binding details."""

    id: int
    provider: AuthProvider
    binding_type: AuthBindingType
    role: AuthRole
    principal_id: Optional[int] = None
    external_group: Optional[str] = None
    created_by: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    principal: Optional[AuthPrincipalResponse] = None

    model_config = ConfigDict(from_attributes=True)


class DeleteResponse(BaseModel):
    """Generic delete response."""

    status: str = "deleted"
    id: int
    message: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)
