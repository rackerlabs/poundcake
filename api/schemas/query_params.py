#  ___                        _  ____      _
# |  _ \ ___  _   _ _ __   __| |/ ___|__ _| | _____
# | |_) / _ \| | | | '_ \ / _` | |   / _` | |/ / _ \
# |  __/ (_) | |_| | | | | (_| | |__| (_| |   <  __/
# |_|   \___/ \__,_|_| |_|\__,_|\____\__,_|_|\_\___|
#
"""Pydantic models for query parameter validation."""

from typing import Optional, Type, Callable
from pydantic import BaseModel, Field, ConfigDict
from fastapi import Request, HTTPException

from api.validation import ProcessingStatus, AlertStatus


def validate_query_params(model_class: Type[BaseModel]) -> Callable[[Request], BaseModel]:
    """
    Dependency factory that validates query parameters against a Pydantic model.

    Rejects unknown query parameters with 422 error.

    Usage:
        @router.get("/endpoint")
        async def my_endpoint(
            params: OvenQueryParams = Depends(validate_query_params(OvenQueryParams)),
        ):
    """

    def dependency(request: Request) -> BaseModel:
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


class OvenQueryParams(BaseModel):
    """Query parameters for GET /api/v1/ovens endpoint."""

    model_config = ConfigDict(extra="forbid")  # Reject unknown parameters in body

    processing_status: Optional[ProcessingStatus] = Field(
        None, description="Filter by processing status (new/pending/processing/complete/failed)"
    )
    req_id: Optional[str] = Field(
        None, min_length=1, max_length=100, description="Filter by request ID"
    )
    alert_id: Optional[int] = Field(None, ge=1, description="Filter by alert ID (positive integer)")
    action_id: Optional[str] = Field(
        None,
        min_length=24,
        max_length=24,
        pattern=r"^[a-f0-9]{24}$",
        description="Filter by StackStorm action/execution ID (24-character hex string)",
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


class AlertQueryParams(BaseModel):
    """Query parameters for GET /api/v1/alerts endpoint."""

    model_config = ConfigDict(extra="forbid")  # Reject unknown parameters in body

    processing_status: Optional[ProcessingStatus] = Field(
        None, description="Filter by processing status (new/pending/processing/complete/failed)"
    )
    alert_status: Optional[AlertStatus] = Field(
        None, description="Filter by alert status (firing/resolved)"
    )
    req_id: Optional[str] = Field(
        None, min_length=1, max_length=100, description="Filter by request ID"
    )
    alert_name: Optional[str] = Field(
        None, min_length=1, max_length=255, description="Filter by alert name"
    )
    limit: int = Field(
        100, ge=1, le=1000, description="Maximum number of results to return (1-1000)"
    )
    offset: int = Field(0, ge=0, description="Number of results to skip for pagination")
