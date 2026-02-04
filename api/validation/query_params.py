#  ___                        _  ____      _
# |  _ \ ___  _   _ _ __   __| |/ ___|__ _| | _____
# | |_) / _ \| | | | '_ \ / _` | |   / _` | |/ / _ \
# |  __/ (_) | |_| | | | | (_| | |__| (_| |   <  __/
# |_|   \___/ \__,_|_| |_|\__,_|\____\__,_|_|\_\___|
#
"""
Query parameter validation schemas and enums for API endpoints.

This module defines valid values and constraints for all query parameters
to ensure proper input validation and return 400 Bad Request for invalid inputs.
"""

from enum import Enum
from typing import Optional
from fastapi import Query


class ProcessingStatus(str, Enum):
    """Valid processing status values for alerts and ovens."""

    NEW = "new"
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETE = "complete"
    FAILED = "failed"


class AlertStatus(str, Enum):
    """Valid alert status values."""

    FIRING = "firing"
    RESOLVED = "resolved"


class ST2Status(str, Enum):
    """Valid StackStorm execution status values."""

    REQUESTED = "requested"
    SCHEDULED = "scheduled"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELED = "canceled"
    CANCELING = "canceling"
    PAUSED = "paused"
    PAUSING = "pausing"
    RESUMING = "resuming"
    PENDING = "pending"


class SortOrder(str, Enum):
    """Valid sort order values."""

    ASC = "asc"
    DESC = "desc"


# Common query parameter constraints
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


def get_processing_status_param() -> Optional[ProcessingStatus]:
    """
    Processing status parameter with enum validation.

    Returns:
        FastAPI Query parameter
    """
    return Query(
        default=None,
        description=f"Filter by processing status. Valid values: {', '.join([s.value for s in ProcessingStatus])}",
    )


def get_alert_status_param() -> Optional[AlertStatus]:
    """
    Alert status parameter with enum validation.

    Returns:
        FastAPI Query parameter
    """
    return Query(
        default=None,
        description=f"Filter by alert status. Valid values: {', '.join([s.value for s in AlertStatus])}",
    )


def get_st2_status_param() -> Optional[ST2Status]:
    """
    StackStorm status parameter with enum validation.

    Returns:
        FastAPI Query parameter
    """
    return Query(
        default=None,
        description=f"Filter by StackStorm execution status. Valid values: {', '.join([s.value for s in ST2Status])}",
    )


def get_sort_order_param(default: SortOrder = SortOrder.DESC) -> SortOrder:
    """
    Sort order parameter with enum validation.

    Args:
        default: Default sort order

    Returns:
        FastAPI Query parameter
    """
    return Query(
        default=default,
        description=f"Sort order. Valid values: {', '.join([s.value for s in SortOrder])}",
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
