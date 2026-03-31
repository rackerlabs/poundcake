"""Read-only Bakery collection jobs executed by PoundCake monitors."""

from __future__ import annotations

import importlib
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import or_, select, text

from api.core.config import get_settings
from api.core.database import SessionLocal
from api.models.models import BakeryMonitorState, Dish, Order, OrderCommunication

ALLOWED_COLLECTOR_TYPES = {
    "monitor_diagnostics",
    "cluster_inventory",
    "ticket_context",
}


class _CollectorModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MonitorDiagnosticsResult(_CollectorModel):
    collector_type: str = "monitor_diagnostics"
    collected_at: datetime
    instance_id: str
    monitor_id: str
    environment_label: str | None = None
    region: str | None = None
    cluster_name: str | None = None
    namespace: str | None = None
    release_name: str | None = None
    tags: list[str] = Field(default_factory=list)
    app_version: str
    health: dict[str, Any]
    bakery_monitor_state: dict[str, Any] | None = None


class ClusterInventoryResult(_CollectorModel):
    collector_type: str = "cluster_inventory"
    collected_at: datetime
    namespace: str | None = None
    pod_count: int
    deployment_count: int
    statefulset_count: int
    service_count: int
    pods: list[dict[str, Any]] = Field(default_factory=list)
    deployments: list[dict[str, Any]] = Field(default_factory=list)
    statefulsets: list[dict[str, Any]] = Field(default_factory=list)
    services: list[dict[str, Any]] = Field(default_factory=list)


class TicketContextResult(_CollectorModel):
    collector_type: str = "ticket_context"
    collected_at: datetime
    criteria: dict[str, Any] = Field(default_factory=dict)
    orders: list[dict[str, Any]] = Field(default_factory=list)
    communications: list[dict[str, Any]] = Field(default_factory=list)
    dishes: list[dict[str, Any]] = Field(default_factory=list)


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _collector_health_snapshot() -> dict[str, Any]:
    settings = get_settings()
    components: dict[str, dict[str, Any]] = {
        "database": {"status": "unknown", "message": ""},
        "stackstorm": {
            "status": "healthy" if settings.stackstorm_url else "unhealthy",
            "message": settings.stackstorm_url or "stackstorm url not configured",
        },
        "redis": {
            "status": "healthy" if settings.redis_url else "unhealthy",
            "message": settings.redis_url or "redis url not configured",
        },
    }
    async with SessionLocal() as db:
        try:
            await db.execute(text("SELECT 1"))
            components["database"] = {"status": "healthy", "message": "Connected"}
        except Exception as exc:  # noqa: BLE001
            components["database"] = {"status": "unhealthy", "message": str(exc)}

    overall = "healthy"
    if any(item["status"] == "unhealthy" for item in components.values()):
        overall = "unhealthy"
    return {
        "status": overall,
        "version": settings.app_version,
        "instance_id": settings.instance_id,
        "components": components,
    }


async def _monitor_diagnostics() -> dict[str, Any]:
    settings = get_settings()
    async with SessionLocal() as db:
        health = await _collector_health_snapshot()
        result = await db.execute(
            select(BakeryMonitorState).where(
                BakeryMonitorState.monitor_id == settings.bakery_monitor_id
            )
        )
        monitor_state = result.scalars().first()

    state_payload = None
    if monitor_state is not None:
        state_payload = {
            "monitor_uuid": monitor_state.monitor_uuid,
            "installation_id": monitor_state.installation_id,
            "last_route_catalog_hash": monitor_state.last_route_catalog_hash,
            "route_sync_dirty": bool(monitor_state.route_sync_dirty),
            "last_heartbeat_status": monitor_state.last_heartbeat_status,
            "last_heartbeat_at": monitor_state.last_heartbeat_at,
            "updated_at": monitor_state.updated_at,
        }

    return MonitorDiagnosticsResult(
        collected_at=_now(),
        instance_id=settings.instance_id,
        monitor_id=settings.bakery_monitor_id,
        environment_label=settings.bakery_monitor_environment_label or None,
        region=settings.bakery_monitor_region or None,
        cluster_name=settings.bakery_monitor_cluster_name or None,
        namespace=settings.bakery_monitor_namespace or None,
        release_name=settings.bakery_monitor_release_name or None,
        tags=list(settings.bakery_monitor_tags or []),
        app_version=settings.app_version,
        health=health,
        bakery_monitor_state=state_payload,
    ).model_dump(mode="json")


def _load_kubernetes_clients():
    k8s_client_module = importlib.import_module("kubernetes.client")
    k8s_config_module = importlib.import_module("kubernetes.config")
    try:
        k8s_config_module.load_incluster_config()
    except Exception:
        k8s_config_module.load_kube_config()
    return k8s_client_module.CoreV1Api(), k8s_client_module.AppsV1Api()


async def _cluster_inventory(parameters: dict[str, Any]) -> dict[str, Any]:
    settings = get_settings()
    namespace = (
        str(parameters.get("namespace") or "").strip()
        or settings.bakery_monitor_namespace
        or "default"
    )
    limit = max(1, min(int(parameters.get("limit") or 50), 200))

    v1, apps_v1 = _load_kubernetes_clients()
    pods = v1.list_namespaced_pod(namespace=namespace, limit=limit).items
    deployments = apps_v1.list_namespaced_deployment(namespace=namespace, limit=limit).items
    statefulsets = apps_v1.list_namespaced_stateful_set(namespace=namespace, limit=limit).items
    services = v1.list_namespaced_service(namespace=namespace, limit=limit).items

    return ClusterInventoryResult(
        collected_at=_now(),
        namespace=namespace,
        pod_count=len(pods),
        deployment_count=len(deployments),
        statefulset_count=len(statefulsets),
        service_count=len(services),
        pods=[
            {
                "name": item.metadata.name,
                "phase": item.status.phase,
                "pod_ip": item.status.pod_ip,
                "node_name": item.spec.node_name,
                "start_time": item.status.start_time,
            }
            for item in pods
        ],
        deployments=[
            {
                "name": item.metadata.name,
                "ready_replicas": item.status.ready_replicas or 0,
                "available_replicas": item.status.available_replicas or 0,
                "replicas": item.spec.replicas or 0,
            }
            for item in deployments
        ],
        statefulsets=[
            {
                "name": item.metadata.name,
                "ready_replicas": item.status.ready_replicas or 0,
                "replicas": item.spec.replicas or 0,
                "service_name": item.spec.service_name,
            }
            for item in statefulsets
        ],
        services=[
            {
                "name": item.metadata.name,
                "type": item.spec.type,
                "cluster_ip": item.spec.cluster_ip,
            }
            for item in services
        ],
    ).model_dump(mode="json")


async def _ticket_context(parameters: dict[str, Any]) -> dict[str, Any]:
    order_id = int(parameters["order_id"]) if parameters.get("order_id") is not None else None
    req_id = str(parameters.get("req_id") or "").strip()
    bakery_ticket_id = str(parameters.get("bakery_ticket_id") or "").strip()
    limit = max(1, min(int(parameters.get("limit") or 20), 100))

    criteria = {
        "order_id": order_id,
        "req_id": req_id or None,
        "bakery_ticket_id": bakery_ticket_id or None,
        "limit": limit,
    }

    async with SessionLocal() as db:
        order_query = select(Order)
        if order_id is not None:
            order_query = order_query.where(Order.id == order_id)
        if req_id:
            order_query = order_query.where(Order.req_id == req_id)
        if bakery_ticket_id:
            order_query = order_query.where(
                or_(
                    Order.bakery_ticket_id == bakery_ticket_id,
                    Order.bakery_comms_id == bakery_ticket_id,
                )
            )
        orders = (
            (await db.execute(order_query.order_by(Order.updated_at.desc()).limit(limit)))
            .scalars()
            .all()
        )

        if not orders and bakery_ticket_id:
            comm_query = select(OrderCommunication).where(
                OrderCommunication.bakery_ticket_id == bakery_ticket_id
            )
            comms = (await db.execute(comm_query.limit(limit))).scalars().all()
            order_ids = [item.order_id for item in comms]
            if order_ids:
                orders = (
                    (
                        await db.execute(
                            select(Order)
                            .where(Order.id.in_(order_ids))
                            .order_by(Order.updated_at.desc())
                        )
                    )
                    .scalars()
                    .all()
                )

        order_ids = [item.id for item in orders]
        req_ids = [item.req_id for item in orders]

        communications: list[OrderCommunication] = []
        if order_ids:
            communications = (
                (
                    await db.execute(
                        select(OrderCommunication)
                        .where(OrderCommunication.order_id.in_(order_ids))
                        .order_by(OrderCommunication.updated_at.desc())
                    )
                )
                .scalars()
                .all()
            )

        dish_query = select(Dish)
        if order_ids:
            dish_query = dish_query.where(
                or_(Dish.order_id.in_(order_ids), Dish.req_id.in_(req_ids))
            )
        elif req_id:
            dish_query = dish_query.where(Dish.req_id == req_id)
        dishes = (
            (await db.execute(dish_query.order_by(Dish.updated_at.desc()).limit(limit)))
            .scalars()
            .all()
        )

    return TicketContextResult(
        collected_at=_now(),
        criteria=criteria,
        orders=[
            {
                "id": item.id,
                "req_id": item.req_id,
                "alert_group_name": item.alert_group_name,
                "alert_status": item.alert_status,
                "processing_status": item.processing_status,
                "remediation_outcome": item.remediation_outcome,
                "bakery_ticket_id": item.bakery_ticket_id,
                "bakery_operation_id": item.bakery_operation_id,
                "bakery_ticket_state": item.bakery_ticket_state,
                "bakery_last_error": item.bakery_last_error,
                "bakery_comms_id": item.bakery_comms_id,
                "created_at": item.created_at,
                "updated_at": item.updated_at,
            }
            for item in orders
        ],
        communications=[
            {
                "id": item.id,
                "order_id": item.order_id,
                "execution_target": item.execution_target,
                "destination_target": item.destination_target,
                "bakery_ticket_id": item.bakery_ticket_id,
                "bakery_operation_id": item.bakery_operation_id,
                "lifecycle_state": item.lifecycle_state,
                "remote_state": item.remote_state,
                "last_error": item.last_error,
                "updated_at": item.updated_at,
            }
            for item in communications
        ],
        dishes=[
            {
                "id": item.id,
                "req_id": item.req_id,
                "order_id": item.order_id,
                "recipe_id": item.recipe_id,
                "run_phase": item.run_phase,
                "processing_status": item.processing_status,
                "execution_status": item.execution_status,
                "execution_ref": item.execution_ref,
                "created_at": item.created_at,
                "updated_at": item.updated_at,
            }
            for item in dishes
        ],
    ).model_dump(mode="json")


async def run_collection_job(
    collector_type: str, parameters: dict[str, Any] | None = None
) -> dict[str, Any]:
    normalized = str(collector_type or "").strip()
    payload = dict(parameters or {})
    if normalized not in ALLOWED_COLLECTOR_TYPES:
        raise ValueError(f"Unsupported collector type: {normalized}")
    if normalized == "monitor_diagnostics":
        return await _monitor_diagnostics()
    if normalized == "cluster_inventory":
        return await _cluster_inventory(payload)
    if normalized == "ticket_context":
        return await _ticket_context(payload)
    raise ValueError(f"Unsupported collector type: {normalized}")
