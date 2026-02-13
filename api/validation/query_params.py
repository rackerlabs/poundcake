#  ___                        _  ____      _
# |  _ \ ___  _   _ _ __   __| |/ ___|__ _| | _____
# | |_) / _ \| | | | '_ \ / _` | |   / _` | |/ / _ \
# |  __/ (_) | |_| | | | | (_| | |__| (_| |   <  __/
# |_|   \___/ \__,_|_| |_|\__,_|\____\__,_|_|\_\___|
#
"""
Query parameter validation schemas using strict Literal types.

This module defines valid values and constraints for all query parameters
to ensure proper input validation and return 400 Bad Request for invalid inputs.
"""

from typing import Optional
from fastapi import Query

# Import strict Literal types for compile-time type safety
from api.types import (
    DishProcessingStatus,
    OrderProcessingStatus,
    AlertStatus as AlertStatusType,
    ST2ExecutionStatus,
    SortOrder as SortOrderType,
)


# =============================================================================
# Common query parameter constraints
# =============================================================================


def get_limit_param(default: int = 100, max_value: int = 1000) -> int:
    """
    Standard limit parameter with validation.

    Args:
        default: Default value if not provided
        max_value: Maximum allowed value

    Returns:
        FastAPI Query parameter
    """
    return Query(
        default=default,
        ge=1,
        le=max_value,
        description=f"Maximum number of results to return (1-{max_value})",
    )


def get_offset_param(default: int = 0) -> int:
    """
    Standard offset parameter with validation.

    Args:
        default: Default value if not provided

    Returns:
        FastAPI Query parameter
    """
    return Query(default=default, ge=0, description="Number of results to skip for pagination")


def get_dish_processing_status_param() -> Optional[DishProcessingStatus]:
    """
    Dish processing status parameter with strict Literal validation.

    Returns:
        FastAPI Query parameter
    """
    return Query(
        default=None,
        description="Filter by processing status. Valid values: new, processing, finalizing, complete, failed, abandoned, timeout, canceled",
    )


def get_order_processing_status_param() -> Optional[OrderProcessingStatus]:
    """
    Order processing status parameter with strict Literal validation.

    Returns:
        FastAPI Query parameter
    """
    return Query(
        default=None,
        description="Filter by processing status. Valid values: new, processing, complete, failed, canceled",
    )


def get_alert_status_param() -> Optional[AlertStatusType]:
    """
    Alert status parameter with strict Literal validation.

    Returns:
        FastAPI Query parameter
    """
    return Query(
        default=None,
        description="Filter by alert status. Valid values: firing, resolved",
    )


def get_st2_status_param() -> Optional[ST2ExecutionStatus]:
    """
    StackStorm status parameter with strict Literal validation.

    Returns:
        FastAPI Query parameter
    """
    return Query(
        default=None,
        description="Filter by StackStorm execution status. Valid values: requested, scheduled, running, succeeded, failed, canceled, canceling, paused, pausing, resuming, pending, timeout, abandoned",
    )


def get_sort_order_param(default: SortOrderType = "desc") -> SortOrderType:
    """
    Sort order parameter with strict Literal validation.

    Args:
        default: Default sort order

    Returns:
        FastAPI Query parameter
    """
    return Query(
        default=default,
        description="Sort order. Valid values: asc, desc",
    )


def get_req_id_param() -> Optional[str]:
    """
    Request ID parameter with validation.

    Returns:
        FastAPI Query parameter
    """
    return Query(
        default=None,
        min_length=1,
        max_length=100,
        description="Filter by request ID (UUID format expected)",
    )


def get_alert_id_param() -> Optional[int]:
    """
    Alert ID parameter with validation.

    Returns:
        FastAPI Query parameter
    """
    return Query(default=None, ge=1, description="Filter by alert ID (positive integer)")


def get_recipe_id_param() -> Optional[int]:
    """
    Recipe ID parameter with validation.

    Returns:
        FastAPI Query parameter
    """
    return Query(default=None, ge=1, description="Filter by recipe ID (positive integer)")


def get_name_param() -> Optional[str]:
    """
    Name parameter with validation.

    Returns:
        FastAPI Query parameter
    """
    return Query(default=None, min_length=1, max_length=255, description="Filter by name")


def get_enabled_param() -> Optional[bool]:
    """
    Enabled parameter with validation.

    Returns:
        FastAPI Query parameter
    """
    return Query(default=None, description="Filter by enabled status (true/false)")


def get_action_id_param() -> Optional[str]:
    """
    Action ID parameter with validation (StackStorm execution ID).

    Returns:
        FastAPI Query parameter
    """
    return Query(
        default=None,
        min_length=24,
        max_length=24,
        pattern=r"^[a-f0-9]{24}$",
        description="Filter by StackStorm action/execution ID (24-character hex string)",
    )
