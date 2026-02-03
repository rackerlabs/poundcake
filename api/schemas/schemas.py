#  ___                        _  ____      _
# |  _ \ ___  _   _ _ __   __| |/ ___|__ _| | _____
# | |_) / _ \| | | | '_ \ / _` | |   / _` | |/ / _ \
# |  __/ (_) | |_| | | | | (_| | |__| (_| |   <  __/
# |_|   \___/ \__,_|_| |_|\__,_|\____\__,_|_|\_\___|
#
"""Pydantic schemas for PoundCake API - CORRECTED to match models."""

from pydantic import BaseModel, ConfigDict, Field
from typing import List, Optional, Dict, Any
from datetime import datetime

# =============================================================================
# Health & Stats
# =============================================================================


class HealthResponse(BaseModel):
    status: str
    version: str
    database: str
    stackstorm: str
    timestamp: datetime


class StatsResponse(BaseModel):
    total_alerts: int
    total_recipes: int
    total_executions: int
    alerts_by_processing_status: Dict[str, int]
    alerts_by_alert_status: Dict[str, int]
    executions_by_status: Dict[str, int]
    recent_alerts: int


# =============================================================================
# Ingredient Schemas
# =============================================================================


class IngredientBase(BaseModel):
    """Base schema for Ingredient creation/updates."""

    task_id: str = Field(..., max_length=100)
    task_name: str = Field(..., max_length=255)
    task_order: int = Field(..., ge=1)
    is_blocking: bool = True
    st2_action: str = Field(..., max_length=255)
    parameters: Optional[Dict[str, Any]] = None
    expected_time_to_completion: int = Field(..., gt=0)
    timeout: int = Field(default=300, gt=0)
    retry_count: int = Field(default=0, ge=0)
    retry_delay: int = Field(default=5, ge=0)
    on_failure: str = Field(default="stop", max_length=50)


class IngredientCreate(IngredientBase):
    """Schema for creating a new ingredient (used in recipe creation)."""

    pass


class IngredientUpdate(BaseModel):
    """Schema for updating an ingredient (all fields optional)."""

    task_id: Optional[str] = Field(None, max_length=100)
    task_name: Optional[str] = Field(None, max_length=255)
    task_order: Optional[int] = Field(None, ge=1)
    is_blocking: Optional[bool] = None
    st2_action: Optional[str] = Field(None, max_length=255)
    parameters: Optional[Dict[str, Any]] = None
    expected_time_to_completion: Optional[int] = Field(None, gt=0)
    timeout: Optional[int] = Field(None, gt=0)
    retry_count: Optional[int] = Field(None, ge=0)
    retry_delay: Optional[int] = Field(None, ge=0)
    on_failure: Optional[str] = Field(None, max_length=50)


class IngredientResponse(IngredientBase):
    """Schema for ingredient responses (includes DB fields)."""

    id: int
    recipe_id: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


# =============================================================================
# Recipe Schemas
# =============================================================================


class RecipeBase(BaseModel):
    """Base schema for Recipe creation/updates."""

    name: str = Field(..., max_length=255)
    description: Optional[str] = None
    enabled: bool = True


class RecipeCreate(RecipeBase):
    """Schema for creating a recipe with ingredients."""

    ingredients: List[IngredientCreate] = Field(..., min_length=1)


class RecipeUpdate(BaseModel):
    """Schema for updating a recipe (all fields optional)."""

    name: Optional[str] = Field(None, max_length=255)
    description: Optional[str] = None
    enabled: Optional[bool] = None


class RecipeResponse(RecipeBase):
    """Schema for recipe responses (includes DB fields)."""

    id: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class RecipeDetailResponse(RecipeResponse):
    """Schema for detailed recipe responses (includes ingredients)."""

    ingredients: List[IngredientResponse] = []


# =============================================================================
# Oven Schemas
# =============================================================================


class OvenBase(BaseModel):
    """Base schema for Oven."""

    req_id: str = Field(..., max_length=100)
    processing_status: str = Field(default="new", max_length=50)


class OvenUpdate(BaseModel):
    """Schema for updating an oven (used by timer service)."""

    processing_status: Optional[str] = Field(None, max_length=50)
    action_id: Optional[str] = Field(None, max_length=255)
    st2_status: Optional[str] = Field(None, max_length=50)
    expected_duration: Optional[int] = None
    actual_duration: Optional[int] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    action_result: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None
    retry_attempt: Optional[int] = None


class OvenResponse(OvenBase):
    """Schema for oven responses."""

    id: int
    alert_id: Optional[int] = None
    recipe_id: int
    ingredient_id: int
    task_order: int
    is_blocking: bool
    action_id: Optional[str] = None
    st2_status: Optional[str] = None
    expected_duration: Optional[int] = None
    actual_duration: Optional[int] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    action_result: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None
    retry_attempt: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class OvenDetailResponse(OvenResponse):
    """Schema for detailed oven responses (includes ingredient info)."""

    ingredient: IngredientResponse


# =============================================================================
# Alert Schemas
# =============================================================================


class AlertBase(BaseModel):
    """Base schema for Alert."""

    req_id: str = Field(..., max_length=100)
    fingerprint: str = Field(..., max_length=255)
    alert_status: str = Field(..., max_length=50)
    alert_name: str = Field(..., max_length=255)
    labels: Dict[str, Any]
    starts_at: datetime


class AlertCreate(AlertBase):
    """Schema for creating an alert."""

    processing_status: str = Field(default="new", max_length=50)
    group_name: Optional[str] = Field(None, max_length=255)
    severity: Optional[str] = Field(None, max_length=50)
    instance: Optional[str] = Field(None, max_length=255)
    prometheus: Optional[str] = Field(None, max_length=255)
    annotations: Optional[Dict[str, Any]] = None
    ends_at: Optional[datetime] = None
    generator_url: Optional[str] = None
    counter: int = 1
    ticket_number: Optional[str] = Field(None, max_length=100)
    raw_data: Optional[Dict[str, Any]] = None


class AlertUpdate(BaseModel):
    """Schema for updating an alert (all fields optional)."""

    alert_status: Optional[str] = Field(None, max_length=50)
    processing_status: Optional[str] = Field(None, max_length=50)
    ends_at: Optional[datetime] = None
    counter: Optional[int] = None
    ticket_number: Optional[str] = Field(None, max_length=100)


class AlertResponse(AlertBase):
    """Schema for alert responses."""

    id: int
    processing_status: str
    group_name: Optional[str] = None
    severity: Optional[str] = None
    instance: Optional[str] = None
    prometheus: Optional[str] = None
    annotations: Optional[Dict[str, Any]] = None
    ends_at: Optional[datetime] = None
    generator_url: Optional[str] = None
    counter: int
    ticket_number: Optional[str] = None
    raw_data: Optional[Dict[str, Any]] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AlertDetailResponse(AlertResponse):
    """Schema for detailed alert responses (includes ovens)."""

    ovens: List[OvenResponse] = []


# ============================================================================
# Operation Response Models
# ============================================================================


class WebhookResponse(BaseModel):
    """Response from webhook endpoint."""

    status: str  # created, counter_incremented, resolved, ignored, no_alerts
    alert_id: Optional[int] = None
    message: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class BakeResponse(BaseModel):
    """Response from bake ovens endpoint."""

    status: str  # baked, ignored
    ovens_created: Optional[int] = None
    recipe_id: Optional[int] = None
    recipe_name: Optional[str] = None
    reason: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class ExecutionResponse(BaseModel):
    """Response from StackStorm execution."""

    id: str  # Execution ID
    status: str  # pending, running, succeeded, failed, etc.
    action: Dict[str, Any]  # Action reference and details
    parameters: Dict[str, Any]  # Execution parameters
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
