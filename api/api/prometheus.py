#  ___                        _  ____      _
# |  _ \ ___  _   _ _ __   __| |/ ___|__ _| | _____
# | |_) / _ \| | | | '_ \ / _` | |   / _` | |/ / _ \
# |  __/ (_) | |_| | | | | (_| | |__| (_| |   <  __/
# |_|   \___/ \__,_|_| |_|\__,_|\____\__,_|_|\_\___|
#
"""Prometheus API endpoints for rule and metric management."""

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from api.api.auth import require_auth_if_enabled
from api.services.prometheus_service import get_prometheus_client
from api.services.prometheus_rule_manager import get_prometheus_rule_manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/prometheus", tags=["prometheus"])


# =============================================================================
# Rule Endpoints
# =============================================================================


@router.get("/rules")
async def list_rules(
    request: Request,
    _user: str | None = Depends(require_auth_if_enabled),
):
    """List all Prometheus alert rules."""
    client = get_prometheus_client()
    try:
        rules = await client.get_rules()
        return {"rules": rules}
    except Exception as e:
        logger.error("Failed to list rules: %s", str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/rule-groups")
async def list_rule_groups(
    request: Request,
    _user: str | None = Depends(require_auth_if_enabled),
):
    """List all Prometheus rule groups."""
    client = get_prometheus_client()
    try:
        groups = await client.get_rule_groups()
        return {"groups": groups}
    except Exception as e:
        logger.error("Failed to list rule groups: %s", str(e))
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# Metric/Label Discovery Endpoints
# =============================================================================


@router.get("/metrics")
async def list_metrics(
    request: Request,
    _user: str | None = Depends(require_auth_if_enabled),
):
    """List all available Prometheus metrics."""
    client = get_prometheus_client()
    try:
        metrics = await client.get_metric_names()
        return {"metrics": metrics}
    except Exception as e:
        logger.error("Failed to list metrics: %s", str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/labels")
async def list_labels(
    request: Request,
    metric: str | None = None,
    _user: str | None = Depends(require_auth_if_enabled),
):
    """List all available label names.

    Args:
        metric: Optional metric name to get labels for a specific metric
    """
    client = get_prometheus_client()
    try:
        labels = await client.get_label_names(metric=metric)
        return {"labels": labels}
    except Exception as e:
        logger.error("Failed to list labels: %s", str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/label-values/{label_name}")
async def list_label_values(
    label_name: str,
    request: Request,
    metric: str | None = None,
    _user: str | None = Depends(require_auth_if_enabled),
):
    """List all values for a specific label.

    Args:
        label_name: The label name to get values for
        metric: Optional metric name to filter values
    """
    client = get_prometheus_client()
    try:
        values = await client.get_label_values(label_name, metric=metric)
        return {"label": label_name, "values": values}
    except Exception as e:
        logger.error("Failed to list label values: %s", str(e))
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# Health & Management Endpoints
# =============================================================================


@router.get("/health")
async def prometheus_health(
    request: Request,
    _user: str | None = Depends(require_auth_if_enabled),
):
    """Check Prometheus health status."""
    client = get_prometheus_client()
    try:
        health = await client.health_check()
        return health
    except Exception as e:
        logger.error("Failed to check Prometheus health: %s", str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/reload")
async def reload_prometheus(
    request: Request,
    _user: str | None = Depends(require_auth_if_enabled),
):
    """Reload Prometheus configuration.

    Note: Requires Prometheus to be started with --web.enable-lifecycle flag.
    """
    client = get_prometheus_client()
    try:
        result = await client.reload_config()
        if result.get("status") == "error":
            raise HTTPException(status_code=500, detail=result.get("message"))
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to reload Prometheus: %s", str(e))
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# Rule CRUD Endpoints
# =============================================================================


@router.post("/rules")
async def create_rule(
    request: Request,
    rule_name: str,
    group_name: str,
    file_name: str,
    _user: str | None = Depends(require_auth_if_enabled),
):
    """Create a new Prometheus alert rule.

    Creates a rule using CRD mode (PrometheusRule CRDs) and/or Git mode
    depending on configuration. CRD mode provides immediate effect,
    while Git mode provides persistence and audit trail via PRs.

    Args:
        rule_name: Name of the alert rule
        group_name: Name of the rule group
        file_name: Name of the YAML file or CRD name

    Request body should contain the rule configuration:
    ```json
    {
        "alert": "HighMemoryUsage",
        "expr": "memory_usage > 90",
        "for": "5m",
        "labels": {"severity": "critical"},
        "annotations": {"summary": "High memory usage detected"}
    }
    ```
    """
    rule_manager = get_prometheus_rule_manager()

    try:
        # Parse request body as rule data
        rule_data: dict[str, Any] = await request.json()

        result = await rule_manager.create_rule(
            rule_name=rule_name,
            group_name=group_name,
            file_name=file_name,
            rule_data=rule_data,
        )

        if result.get("status") == "error":
            raise HTTPException(status_code=400, detail=result.get("message"))

        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to create rule: %s", str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/rules/{rule_name}")
async def update_rule(
    rule_name: str,
    request: Request,
    group_name: str,
    file_name: str,
    _user: str | None = Depends(require_auth_if_enabled),
):
    """Update a Prometheus alert rule.

    Updates a rule using CRD mode (PrometheusRule CRDs) and/or Git mode
    depending on configuration. CRD mode provides immediate effect,
    while Git mode provides persistence and audit trail via PRs.

    Args:
        rule_name: Name of the alert rule (path parameter)
        group_name: Name of the rule group
        file_name: Name of the YAML file or CRD name

    Request body should contain the updated rule configuration.
    """
    rule_manager = get_prometheus_rule_manager()

    try:
        # Parse request body as rule data
        rule_data: dict[str, Any] = await request.json()

        result = await rule_manager.update_rule(
            rule_name=rule_name,
            group_name=group_name,
            file_name=file_name,
            rule_data=rule_data,
        )

        if result.get("status") == "error":
            raise HTTPException(status_code=400, detail=result.get("message"))

        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to update rule: %s", str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/rules/{rule_name}")
async def delete_rule(
    rule_name: str,
    request: Request,
    group_name: str,
    file_name: str,
    _user: str | None = Depends(require_auth_if_enabled),
):
    """Delete a Prometheus alert rule.

    Deletes a rule using CRD mode (PrometheusRule CRDs) and/or Git mode
    depending on configuration. CRD mode provides immediate effect,
    while Git mode creates a PR for the deletion.

    Args:
        rule_name: Name of the alert rule (path parameter)
        group_name: Name of the rule group
        file_name: Name of the YAML file or CRD name
    """
    rule_manager = get_prometheus_rule_manager()

    try:
        result = await rule_manager.delete_rule(
            rule_name=rule_name,
            group_name=group_name,
            file_name=file_name,
        )

        if result.get("status") == "error":
            raise HTTPException(status_code=400, detail=result.get("message"))

        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to delete rule: %s", str(e))
        raise HTTPException(status_code=500, detail=str(e))
