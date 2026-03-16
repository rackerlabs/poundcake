#  ___                        _  ____      _
# |  _ \ ___  _   _ _ __   __| |/ ___|__ _| | _____
# | |_) / _ \| | | | '_ \ / _` | |   / _` | |/ / _ \
# |  __/ (_) | |_| | | | | (_| | |__| (_| |   <  __/
# |_|   \___/ \__,_|_| |_|\__,_|\____\__,_|_|\_\___|
#
"""Pydantic models for query parameter validation."""

from typing import Optional, Type, Callable, TypeVar
from pydantic import BaseModel, Field, ConfigDict
from fastapi import Request, HTTPException

from api.types import DishProcessingStatus, OrderProcessingStatus, AlertStatus
from api.types import SuppressionStatus

TQueryParams = TypeVar("TQueryParams", bound=BaseModel)


def validate_query_params(model_class: Type[TQueryParams]) -> Callable[[Request], TQueryParams]:
    """
    Dependency factory that validates query parameters against a Pydantic model.

    Rejects unknown query parameters with 422 error.
    """

    def dependency(request: Request) -> TQueryParams:
        # Get allowed field names from Pydantic model
        allowed_params = set(model_class.model_fields.keys())

        # Get actual query parameters from request
        query_params = set(request.query_params.keys())

        # Check for unknown parameters
        unknown_params = query_params - allowed_params

        if unknown_params:
            raise HTTPException(
                status_code=422,
                detail={
                    "error": "Unknown query parameters",
                    "unknown_parameters": sorted(list(unknown_params)),
                    "allowed_parameters": sorted(list(allowed_params)),
                },
            )

        # If validation passes, instantiate the model from query params
        return model_class(**request.query_params)

    return dependency


class DishQueryParams(BaseModel):
    """Query parameters for GET /api/v1/dishes endpoint."""

    model_config = ConfigDict(extra="forbid")  # Reject unknown parameters in body

    processing_status: Optional[DishProcessingStatus] = Field(
        None,
        description="Filter by processing status (new/processing/finalizing/complete/failed/abandoned/timeout/canceled)",
    )
    req_id: Optional[str] = Field(
        None, min_length=1, max_length=100, description="Filter by request ID"
    )
    order_id: Optional[int] = Field(None, ge=1, description="Filter by order ID (positive integer)")
    execution_ref: Optional[str] = Field(
        None,
        min_length=1,
        max_length=100,
        description="Filter by execution reference",
    )
    limit: int = Field(
        100, ge=1, le=1000, description="Maximum number of results to return (1-1000)"
    )
    offset: int = Field(0, ge=0, description="Number of results to skip for pagination")


class RecipeQueryParams(BaseModel):
    """Query parameters for GET /api/v1/recipes/ endpoint."""

    model_config = ConfigDict(extra="forbid")  # Reject unknown parameters in body

    name: Optional[str] = Field(
        None, min_length=1, max_length=255, description="Filter by recipe name"
    )
    enabled: Optional[bool] = Field(None, description="Filter by enabled status (true/false)")
    limit: int = Field(
        100, ge=1, le=1000, description="Maximum number of results to return (1-1000)"
    )
    offset: int = Field(0, ge=0, description="Number of results to skip for pagination")


class IngredientQueryParams(BaseModel):
    """Query parameters for GET /api/v1/ingredients endpoint."""

    model_config = ConfigDict(extra="forbid")

    execution_target: Optional[str] = Field(
        None, min_length=1, max_length=100, description="Filter by execution target"
    )
    task_key_template: Optional[str] = Field(
        None, min_length=1, max_length=255, description="Filter by task key template"
    )
    limit: int = Field(
        100, ge=1, le=1000, description="Maximum number of results to return (1-1000)"
    )
    offset: int = Field(0, ge=0, description="Number of results to skip for pagination")


class OrderQueryParams(BaseModel):
    """Query parameters for GET /api/v1/orders endpoint."""

    model_config = ConfigDict(extra="forbid")  # Reject unknown parameters in body

    processing_status: Optional[OrderProcessingStatus] = Field(
        None,
        description=(
            "Filter by processing status "
            "(new/processing/waiting_clear/escalation/resolving/complete/failed/canceled)"
        ),
    )
    alert_status: Optional[AlertStatus] = Field(
        None, description="Filter by alert status (firing/resolved)"
    )
    req_id: Optional[str] = Field(
        None, min_length=1, max_length=100, description="Filter by request ID"
    )
    alert_group_name: Optional[str] = Field(
        None, min_length=1, max_length=255, description="Filter by alert group name"
    )
    limit: int = Field(
        100, ge=1, le=1000, description="Maximum number of results to return (1-1000)"
    )
    offset: int = Field(0, ge=0, description="Number of results to skip for pagination")


class SuppressionQueryParams(BaseModel):
    """Query parameters for GET /api/v1/suppressions endpoint."""

    model_config = ConfigDict(extra="forbid")

    status: Optional[SuppressionStatus] = Field(
        None, description="Filter by suppression status (scheduled|active|expired|canceled)"
    )
    enabled: Optional[bool] = Field(None, description="Filter by enabled state")
    scope: Optional[str] = Field(None, description="Filter by scope (all|matchers)")
    limit: int = Field(
        100, ge=1, le=1000, description="Maximum number of results to return (1-1000)"
    )
    offset: int = Field(0, ge=0, description="Number of results to skip for pagination")


class SuppressedActivityQueryParams(BaseModel):
    """Query parameters for GET /api/v1/activity/suppressed endpoint."""

    model_config = ConfigDict(extra="forbid")

    suppression_id: Optional[int] = Field(None, ge=1, description="Filter by suppression ID")
    limit: int = Field(
        100, ge=1, le=1000, description="Maximum number of results to return (1-1000)"
    )
    offset: int = Field(0, ge=0, description="Number of results to skip for pagination")


class BakeryOperationQueryParams(BaseModel):
    """Query parameters for GET /api/v1/ticketing/bakery endpoint."""

    model_config = ConfigDict(extra="forbid")

    status: Optional[str] = Field(None, description="Filter by operation/summary status")
    limit: int = Field(
        100, ge=1, le=1000, description="Maximum number of results to return (1-1000)"
    )
    offset: int = Field(0, ge=0, description="Number of results to skip for pagination")


class ObservabilityActivityQueryParams(BaseModel):
    """Query parameters for GET /api/v1/observability/activity endpoint."""

    model_config = ConfigDict(extra="forbid")

    type: Optional[str] = Field(None, description="Filter by activity type")
    limit: int = Field(50, ge=1, le=250, description="Maximum number of results to return (1-250)")
    offset: int = Field(0, ge=0, description="Number of results to skip for pagination")


class CommunicationActivityQueryParams(BaseModel):
    """Query parameters for GET /api/v1/communications/activity endpoint."""

    model_config = ConfigDict(extra="forbid")

    status: Optional[str] = Field(None, description="Filter by lifecycle or remote status")
    channel: Optional[str] = Field(None, description="Filter by communication channel")
    limit: int = Field(
        100, ge=1, le=1000, description="Maximum number of results to return (1-1000)"
    )
    offset: int = Field(0, ge=0, description="Number of results to skip for pagination")
