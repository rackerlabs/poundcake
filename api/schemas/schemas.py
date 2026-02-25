#  ___                        _  ____      _
# |  _ \ ___  _   _ _ __   __| |/ ___|__ _| | _____
# | |_) / _ \| | | | '_ \ / _` | |   / _` | |/ / _ \
# |  __/ (_) | |_| | | | | (_| | |__| (_| |   <  __/
# |_|   \___/ \__,_|_| |_|\__,_|\____\__,_|_|\_\___|
#
"""Pydantic schemas for PoundCake API."""

from pydantic import BaseModel, ConfigDict, Field
from typing import List, Optional, Dict, Any
from datetime import datetime

from api.types import (
    DishProcessingStatus,
    OrderProcessingStatus,
    AlertStatus,
    OnSuccessAction,
    OnFailureAction,
    SuppressionScope,
    SuppressionStatus,
    SuppressionMatcherOperator,
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


# =============================================================================
# Ingredient Schemas (Global)
# =============================================================================


class IngredientBase(BaseModel):
    """Base schema for Ingredient creation/updates."""

    task_id: str = Field(..., max_length=100)
    task_name: str = Field(..., max_length=255)

    action_id: Optional[str] = Field(None, max_length=100)
    action_payload: Optional[str] = None
    action_parameters: Optional[Dict[str, Any]] = None

    source_type: str = Field(default="undefined", max_length=50)
    is_blocking: bool = True
    expected_duration_sec: int = Field(..., gt=0)
    timeout_duration_sec: int = Field(default=300, gt=0)
    retry_count: int = Field(default=0, ge=0)
    retry_delay: int = Field(default=5, ge=0)
    on_failure: OnFailureAction = Field(default="stop")


class IngredientCreate(IngredientBase):
    """Schema for creating a new global ingredient."""

    pass


class IngredientUpdate(BaseModel):
    """Schema for updating an ingredient (all fields optional)."""

    task_id: Optional[str] = Field(None, max_length=100)
    task_name: Optional[str] = Field(None, max_length=255)
    action_id: Optional[str] = Field(None, max_length=100)
    action_payload: Optional[str] = None
    action_parameters: Optional[Dict[str, Any]] = None
    source_type: Optional[str] = Field(None, max_length=50)
    is_blocking: Optional[bool] = None
    expected_duration_sec: Optional[int] = Field(None, gt=0)
    timeout_duration_sec: Optional[int] = Field(None, gt=0)
    retry_count: Optional[int] = Field(None, ge=0)
    retry_delay: Optional[int] = Field(None, ge=0)
    on_failure: Optional[OnFailureAction] = None


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
    input_parameters: Optional[Dict[str, Any]] = None


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
    source_type: str = Field(default="undefined", max_length=50)
    workflow_id: Optional[str] = Field(None, max_length=255)
    workflow_payload: Optional[Dict[str, Any]] = None
    workflow_parameters: Optional[Dict[str, Any]] = None


class RecipeCreate(RecipeBase):
    """Schema for creating a recipe with recipe_ingredients."""

    recipe_ingredients: List[RecipeIngredientCreate] = Field(..., min_length=1)


class RecipeUpdate(BaseModel):
    """Schema for updating a recipe (all fields optional)."""

    name: Optional[str] = Field(None, max_length=255)
    description: Optional[str] = None
    enabled: Optional[bool] = None
    source_type: Optional[str] = Field(None, max_length=50)
    workflow_id: Optional[str] = Field(None, max_length=255)
    workflow_payload: Optional[Dict[str, Any]] = None
    workflow_parameters: Optional[Dict[str, Any]] = None


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


# =============================================================================
# Dish Schemas
# =============================================================================


class DishBase(BaseModel):
    """Base schema for Dish."""

    req_id: str = Field(..., max_length=100)
    processing_status: DishProcessingStatus = Field(default="new")


class DishUpdate(BaseModel):
    """Schema for updating a dish."""

    processing_status: Optional[DishProcessingStatus] = None
    status: Optional[str] = Field(None, max_length=50)
    workflow_execution_id: Optional[str] = Field(None, max_length=100)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    expected_duration_sec: Optional[int] = None
    actual_duration_sec: Optional[int] = None
    result: Optional[Any] = None
    error_message: Optional[str] = None
    retry_attempt: Optional[int] = None


class DishResponse(DishBase):
    """Schema for dish responses."""

    id: int
    order_id: Optional[int] = None
    recipe_id: int
    workflow_execution_id: Optional[str] = None
    status: Optional[str] = None
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
    bakery_comms_id: Optional[str] = Field(None, max_length=36)
    fingerprint_when_active: Optional[str] = Field(None, max_length=255)


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
    fingerprint_when_active: Optional[str] = Field(None, max_length=255)


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
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class DishIngredientUpsert(BaseModel):
    """Upsert payload for dish ingredient execution results."""

    st2_execution_id: Optional[str] = None
    task_id: Optional[str] = None
    status: Optional[str] = None
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
    task_id: Optional[str] = None
    st2_execution_id: Optional[str] = None
    status: Optional[str] = None
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
    by_alertname_json: Optional[Dict[str, Any]] = None
    by_severity_json: Optional[Dict[str, Any]] = None
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


class BakeryOperationRecord(BaseModel):
    source: str
    reference_id: str
    ticket_id: Optional[str] = None
    operation_id: Optional[str] = None
    status: Optional[str] = None
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


class CookResponse(BaseModel):
    """Response from cook dishes endpoint."""

    status: str  # cooked, ignored
    dishes_created: Optional[int] = None
    recipe_id: Optional[int] = None
    recipe_name: Optional[str] = None
    reason: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class ExecutionResponse(BaseModel):
    """Response from StackStorm execution."""

    id: str  # Execution ID
    status: str  # pending, running, succeeded, failed, etc.
    action: Dict[str, Any]  # Action reference and details
    parameters: Dict[str, Any] = Field(
        default_factory=dict
    )  # Execution parameters (optional in ST2 responses)
    result: Optional[Dict[str, Any]] = None
    start_timestamp: Optional[str] = None
    end_timestamp: Optional[str] = None

    model_config = ConfigDict(from_attributes=True, extra="allow")  # Allow additional ST2 fields


class SessionResponse(BaseModel):
    """Response from login endpoint."""

    session_id: str
    username: str
    expires_at: str  # ISO format datetime
    token_type: str = "Bearer"

    model_config = ConfigDict(from_attributes=True)


class DeleteResponse(BaseModel):
    """Generic delete response."""

    status: str = "deleted"
    id: int
    message: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)
