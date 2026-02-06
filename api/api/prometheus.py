#  ___                        _  ____      _
# |  _ \ ___  _   _ _ __   __| |/ ___|__ _| | _____
# | |_) / _ \| | | | '_ \ / _` | |   / _` | |/ / _ \
# |  __/ (_) | |_| | | | | (_| | |__| (_| |   <  __/
# |_|   \___/ \__,_|_| |_|\__,_|\____\__,_|_|\_\___|
#
"""Prometheus API endpoints for rule and metric management."""

from api.core.logging import get_logger
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from api.api.auth import require_auth_if_enabled
from api.services.prometheus_service import get_prometheus_client
from api.services.prometheus_rule_manager import get_prometheus_rule_manager
from api.services.prometheus_crd_manager import PrometheusCRDManager
from api.core.config import get_settings

logger = get_logger(__name__)

# REMOVED hardcoded prefix to allow main.py to handle /api/v1 nesting
router = APIRouter(tags=["prometheus"])


# =============================================================================
# Rule Endpoints
# =============================================================================


@router.get("/prometheus/rules")
async def list_rules(
    request: Request,
    _user: str | None = Depends(require_auth_if_enabled),
):
    """List all Prometheus alert rules.

    If prometheus.useCrds is enabled, reads from PrometheusRule CRDs.
    Otherwise, queries the Prometheus API directly.
    """
    settings = get_settings()

    try:
        if settings.prometheus_use_crds:
            # Read from Kubernetes PrometheusRule CRDs
            crd_manager = PrometheusCRDManager()
            crd_list = await crd_manager.get_prometheus_rules()

            # Flatten CRDs into rule list format similar to Prometheus API
            rules = []
            for crd in crd_list:
                crd_name = crd.get("metadata", {}).get("name", "")
                crd_namespace = crd.get("metadata", {}).get("namespace", "")
                spec = crd.get("spec", {})
                groups = spec.get("groups", [])

                for group in groups:
                    group_name = group.get("name", "")
                    group_interval = group.get("interval", "")

                    for rule in group.get("rules", []):
                        if rule.get("alert"):  # Only include alerting rules
                            rules.append(
                                {
                                    "group": group_name,
                                    "crd": crd_name,
                                    "namespace": crd_namespace,
                                    "interval": group_interval,
                                    "name": rule.get("alert", ""),
                                    "query": rule.get("expr", ""),
                                    "duration": rule.get("for", ""),
                                    "labels": rule.get("labels", {}),
                                    "annotations": rule.get("annotations", {}),
                                    "state": "unknown",  # CRDs don't have runtime state
                                    "health": "unknown",  # CRDs don't have health status
                                }
                            )

            logger.info(
                "Fetched rules from CRDs",
                extra={
                    "req_id": request.state.req_id,
                    "crd_count": len(crd_list),
                    "rule_count": len(rules),
                },
            )
            return {"rules": rules, "source": "crds"}
        else:
            # Read from Prometheus API
            client = get_prometheus_client()
            rules = await client.get_rules()
            return {"rules": rules, "source": "prometheus-api"}

    except Exception as e:
        logger.error(
            "Failed to list rules",
            extra={"req_id": request.state.req_id, "method": request.method, "error": str(e)},
        )
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/prometheus/rule-groups")
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


@router.get("/prometheus/metrics")
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


@router.get("/prometheus/labels")
async def list_labels(
    request: Request,
    metric: str | None = None,
    _user: str | None = Depends(require_auth_if_enabled),
):
    """List all available label names."""
    client = get_prometheus_client()
    try:
        labels = await client.get_label_names(metric=metric)
        return {"labels": labels}
    except Exception as e:
        logger.error("Failed to list labels: %s", str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/prometheus/label-values/{label_name}")
async def list_label_values(
    label_name: str,
    request: Request,
    metric: str | None = None,
    _user: str | None = Depends(require_auth_if_enabled),
):
    """List all values for a specific label."""
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


@router.get("/prometheus/health")
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


@router.post("/prometheus/reload")
async def reload_prometheus(
    request: Request,
    _user: str | None = Depends(require_auth_if_enabled),
):
    """Reload Prometheus configuration."""
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


@router.post("/prometheus/rules")
async def create_rule(
    request: Request,
    rule_name: str,
    group_name: str,
    file_name: str,
    _user: str | None = Depends(require_auth_if_enabled),
):
    """Create a new Prometheus alert rule."""
    rule_manager = get_prometheus_rule_manager()
    try:
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
    except Exception as e:
        logger.error("Failed to create rule: %s", str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/prometheus/rules/{rule_name}")
async def update_rule(
    rule_name: str,
    request: Request,
    group_name: str,
    file_name: str,
    _user: str | None = Depends(require_auth_if_enabled),
):
    """Update a Prometheus alert rule."""
    rule_manager = get_prometheus_rule_manager()
    try:
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
    except Exception as e:
        logger.error("Failed to update rule: %s", str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/prometheus/rules/{rule_name}")
async def delete_rule(
    rule_name: str,
    request: Request,
    group_name: str,
    file_name: str,
    _user: str | None = Depends(require_auth_if_enabled),
):
    """Delete a Prometheus alert rule."""
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
    except Exception as e:
        logger.error("Failed to delete rule: %s", str(e))
        raise HTTPException(status_code=500, detail=str(e))
