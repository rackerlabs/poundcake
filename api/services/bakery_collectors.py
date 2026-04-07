"""Read-only Bakery collection jobs executed by PoundCake monitors."""

from __future__ import annotations

import importlib
from decimal import Decimal, InvalidOperation
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
    limit: int
    node_count: int
    ready_node_count: int
    storage_class_count: int
    persistent_volume_count: int
    persistent_volume_claim_count: int
    pod_count: int
    deployment_count: int
    statefulset_count: int
    service_count: int
    cluster_summary: dict[str, Any] = Field(default_factory=dict)
    report: dict[str, Any] = Field(default_factory=dict)
    nodes: list[dict[str, Any]] = Field(default_factory=list)
    storage_classes: list[dict[str, Any]] = Field(default_factory=list)
    persistent_volumes: list[dict[str, Any]] = Field(default_factory=list)
    persistent_volume_claims: list[dict[str, Any]] = Field(default_factory=list)
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
    return (
        k8s_client_module.CoreV1Api(),
        k8s_client_module.AppsV1Api(),
        k8s_client_module.StorageV1Api(),
    )


_QUANTITY_MULTIPLIERS: dict[str, Decimal] = {
    "": Decimal(1),
    "n": Decimal("0.000000001"),
    "u": Decimal("0.000001"),
    "m": Decimal("0.001"),
    "k": Decimal(1000),
    "K": Decimal(1000),
    "M": Decimal(1000**2),
    "G": Decimal(1000**3),
    "T": Decimal(1000**4),
    "P": Decimal(1000**5),
    "E": Decimal(1000**6),
    "Ki": Decimal(1024),
    "Mi": Decimal(1024**2),
    "Gi": Decimal(1024**3),
    "Ti": Decimal(1024**4),
    "Pi": Decimal(1024**5),
    "Ei": Decimal(1024**6),
}


def _metadata_map(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {str(key): str(item) for key, item in value.items()}


def _parse_quantity(value: Any) -> Decimal:
    text = str(value or "").strip()
    if not text:
        return Decimal(0)
    suffix = ""
    numeric = text
    for candidate in sorted(_QUANTITY_MULTIPLIERS, key=len, reverse=True):
        if candidate and text.endswith(candidate):
            suffix = candidate
            numeric = text[: -len(candidate)]
            break
    try:
        return Decimal(numeric) * _QUANTITY_MULTIPLIERS[suffix]
    except (InvalidOperation, KeyError):
        return Decimal(0)


def _parse_cpu_millicores(value: Any) -> int:
    return int((_parse_quantity(value) * Decimal(1000)).to_integral_value())


def _parse_int_quantity(value: Any) -> int:
    return int(_parse_quantity(value).to_integral_value())


def _parse_storage_bytes(value: Any) -> int:
    return int(_parse_quantity(value).to_integral_value())


def _node_roles(labels: dict[str, str]) -> list[str]:
    roles: list[str] = []
    for key, value in labels.items():
        if key.startswith("node-role.kubernetes.io/"):
            suffix = key.split("/", 1)[1].strip()
            roles.append(suffix or "worker")
        elif key == "kubernetes.io/role" and value:
            roles.append(str(value))
    return sorted(set(roles))


def _node_conditions(status: Any) -> tuple[list[dict[str, Any]], bool]:
    rows: list[dict[str, Any]] = []
    ready = False
    for item in getattr(status, "conditions", []) or []:
        payload = {
            "type": getattr(item, "type", None),
            "status": getattr(item, "status", None),
            "reason": getattr(item, "reason", None),
            "message": getattr(item, "message", None),
            "last_transition_time": getattr(item, "last_transition_time", None),
            "last_heartbeat_time": getattr(item, "last_heartbeat_time", None),
        }
        rows.append(payload)
        if payload["type"] == "Ready" and str(payload["status"]).lower() == "true":
            ready = True
    return rows, ready


def _address_rows(status: Any) -> list[dict[str, Any]]:
    return [
        {"type": getattr(item, "type", None), "address": getattr(item, "address", None)}
        for item in (getattr(status, "addresses", []) or [])
    ]


def _taint_rows(spec: Any) -> list[dict[str, Any]]:
    return [
        {
            "key": getattr(item, "key", None),
            "value": getattr(item, "value", None),
            "effect": getattr(item, "effect", None),
        }
        for item in (getattr(spec, "taints", []) or [])
    ]


def _resource_totals(values: list[dict[str, Any]]) -> dict[str, int]:
    totals = {
        "cpu_millicores": 0,
        "memory_bytes": 0,
        "ephemeral_storage_bytes": 0,
        "pods": 0,
    }
    for value in values:
        totals["cpu_millicores"] += int(value.get("cpu_millicores") or 0)
        totals["memory_bytes"] += int(value.get("memory_bytes") or 0)
        totals["ephemeral_storage_bytes"] += int(value.get("ephemeral_storage_bytes") or 0)
        totals["pods"] += int(value.get("pods") or 0)
    return totals


def _node_resource_summary(raw: dict[str, Any]) -> dict[str, int]:
    return {
        "cpu_millicores": _parse_cpu_millicores(raw.get("cpu")),
        "memory_bytes": _parse_storage_bytes(raw.get("memory")),
        "ephemeral_storage_bytes": _parse_storage_bytes(raw.get("ephemeral-storage")),
        "pods": _parse_int_quantity(raw.get("pods")),
    }


def _service_ports(service: Any) -> list[str]:
    ports: list[str] = []
    for item in getattr(service.spec, "ports", []) or []:
        base = f"{getattr(item, 'port', '?')}/{getattr(item, 'protocol', 'TCP')}"
        target_port = getattr(item, "target_port", None)
        ports.append(f"{base} -> {target_port}" if target_port else base)
    return ports


def _build_inventory_report(
    *,
    namespace: str,
    limit: int,
    summary: dict[str, Any],
) -> dict[str, Any]:
    return {
        "title": "Cluster inventory report",
        "generated_at": _now(),
        "scope": {
            "namespace": namespace,
            "namespace_row_limit": limit,
            "cluster_wide_sections": ["nodes", "storage_classes", "persistent_volumes"],
            "namespace_scoped_sections": [
                "persistent_volume_claims",
                "pods",
                "deployments",
                "statefulsets",
                "services",
            ],
        },
        "highlights": [
            f"{summary['ready_node_count']} of {summary['node_count']} nodes ready",
            (
                f"{summary['persistent_volume_count']} persistent volumes across "
                f"{summary['storage_class_count']} storage classes"
            ),
            (
                f"{summary['pod_count']} pods, {summary['deployment_count']} deployments, "
                f"{summary['statefulset_count']} statefulsets in namespace {namespace}"
            ),
        ],
        "sections": [
            {
                "id": "nodes",
                "title": "Node inventory",
                "summary": (
                    f"{summary['node_count']} nodes, {summary['ready_node_count']} ready, "
                    f"{summary['unschedulable_node_count']} unschedulable"
                ),
            },
            {
                "id": "storage",
                "title": "Storage topology",
                "summary": (
                    f"{summary['storage_class_count']} storage classes, "
                    f"{summary['persistent_volume_count']} persistent volumes, "
                    f"{summary['persistent_volume_claim_count']} persistent volume claims"
                ),
            },
            {
                "id": "workloads",
                "title": "Namespace workload snapshot",
                "summary": (
                    f"{summary['pod_count']} pods, {summary['deployment_count']} deployments, "
                    f"{summary['statefulset_count']} statefulsets, {summary['service_count']} services"
                ),
            },
        ],
    }


async def _cluster_inventory(parameters: dict[str, Any]) -> dict[str, Any]:
    settings = get_settings()
    namespace = (
        str(parameters.get("namespace") or "").strip()
        or settings.bakery_monitor_namespace
        or "default"
    )
    limit = max(1, min(int(parameters.get("limit") or 50), 200))

    v1, apps_v1, storage_v1 = _load_kubernetes_clients()
    nodes = v1.list_node().items
    storage_classes = storage_v1.list_storage_class().items
    persistent_volumes = v1.list_persistent_volume().items
    persistent_volume_claims = v1.list_namespaced_persistent_volume_claim(
        namespace=namespace,
        limit=limit,
    ).items
    pods = v1.list_namespaced_pod(namespace=namespace, limit=limit).items
    deployments = apps_v1.list_namespaced_deployment(namespace=namespace, limit=limit).items
    statefulsets = apps_v1.list_namespaced_stateful_set(namespace=namespace, limit=limit).items
    services = v1.list_namespaced_service(namespace=namespace, limit=limit).items

    node_rows: list[dict[str, Any]] = []
    capacity_rows: list[dict[str, Any]] = []
    allocatable_rows: list[dict[str, Any]] = []
    ready_node_count = 0
    unschedulable_node_count = 0
    for item in nodes:
        labels = _metadata_map(getattr(item.metadata, "labels", None))
        annotations = _metadata_map(getattr(item.metadata, "annotations", None))
        conditions, ready = _node_conditions(item.status)
        roles = _node_roles(labels)
        schedulable = not bool(getattr(item.spec, "unschedulable", False))
        capacity = _metadata_map(getattr(item.status, "capacity", None))
        allocatable = _metadata_map(getattr(item.status, "allocatable", None))
        node_info = getattr(item.status, "node_info", None)
        if ready:
            ready_node_count += 1
        if not schedulable:
            unschedulable_node_count += 1
        capacity_summary = _node_resource_summary(capacity)
        allocatable_summary = _node_resource_summary(allocatable)
        capacity_rows.append(capacity_summary)
        allocatable_rows.append(allocatable_summary)
        node_rows.append(
            {
                "name": item.metadata.name,
                "ready": ready,
                "schedulable": schedulable,
                "roles": roles,
                "labels": labels,
                "annotations": annotations,
                "taints": _taint_rows(item.spec),
                "addresses": _address_rows(item.status),
                "conditions": conditions,
                "kubelet_version": getattr(node_info, "kubelet_version", None),
                "container_runtime_version": getattr(node_info, "container_runtime_version", None),
                "operating_system": getattr(node_info, "operating_system", None),
                "os_image": getattr(node_info, "os_image", None),
                "architecture": getattr(node_info, "architecture", None),
                "kernel_version": getattr(node_info, "kernel_version", None),
                "capacity_cpu": capacity.get("cpu"),
                "capacity_memory": capacity.get("memory"),
                "capacity_ephemeral_storage": capacity.get("ephemeral-storage"),
                "capacity_pods": capacity.get("pods"),
                "allocatable_cpu": allocatable.get("cpu"),
                "allocatable_memory": allocatable.get("memory"),
                "allocatable_ephemeral_storage": allocatable.get("ephemeral-storage"),
                "allocatable_pods": allocatable.get("pods"),
            }
        )

    storage_class_rows = [
        {
            "name": item.metadata.name,
            "provisioner": item.provisioner,
            "reclaim_policy": item.reclaim_policy,
            "volume_binding_mode": item.volume_binding_mode,
            "allow_volume_expansion": bool(item.allow_volume_expansion),
            "mount_options": list(item.mount_options or []),
            "labels": _metadata_map(getattr(item.metadata, "labels", None)),
            "annotations": _metadata_map(getattr(item.metadata, "annotations", None)),
        }
        for item in storage_classes
    ]
    persistent_volume_rows = [
        {
            "name": item.metadata.name,
            "phase": getattr(item.status, "phase", None),
            "storage_class_name": getattr(item.spec, "storage_class_name", None),
            "capacity": _metadata_map(getattr(item.spec, "capacity", None)).get("storage"),
            "access_modes": list(getattr(item.spec, "access_modes", []) or []),
            "reclaim_policy": getattr(item.spec, "persistent_volume_reclaim_policy", None),
            "claim_ref": (
                f"{item.spec.claim_ref.namespace}/{item.spec.claim_ref.name}"
                if getattr(item.spec, "claim_ref", None)
                else None
            ),
            "volume_mode": getattr(item.spec, "volume_mode", None),
            "csi_driver": getattr(getattr(item.spec, "csi", None), "driver", None),
            "labels": _metadata_map(getattr(item.metadata, "labels", None)),
            "annotations": _metadata_map(getattr(item.metadata, "annotations", None)),
        }
        for item in persistent_volumes
    ]
    persistent_volume_claim_rows = [
        {
            "name": item.metadata.name,
            "namespace": item.metadata.namespace,
            "phase": getattr(item.status, "phase", None),
            "storage_class_name": getattr(item.spec, "storage_class_name", None),
            "requested_storage": _metadata_map(
                getattr(getattr(item.spec, "resources", None), "requests", None)
            ).get("storage"),
            "access_modes": list(getattr(item.spec, "access_modes", []) or []),
            "volume_name": getattr(item.spec, "volume_name", None),
            "volume_mode": getattr(item.spec, "volume_mode", None),
            "labels": _metadata_map(getattr(item.metadata, "labels", None)),
            "annotations": _metadata_map(getattr(item.metadata, "annotations", None)),
        }
        for item in persistent_volume_claims
    ]
    pod_rows = [
        {
            "name": item.metadata.name,
            "phase": item.status.phase,
            "pod_ip": item.status.pod_ip,
            "node_name": item.spec.node_name,
            "restart_count": sum(
                int(getattr(status, "restart_count", 0))
                for status in (getattr(item.status, "container_statuses", None) or [])
            ),
            "start_time": item.status.start_time,
            "qos_class": getattr(item.status, "qos_class", None),
            "labels": _metadata_map(getattr(item.metadata, "labels", None)),
        }
        for item in pods
    ]
    deployment_rows = [
        {
            "name": item.metadata.name,
            "ready_replicas": item.status.ready_replicas or 0,
            "available_replicas": item.status.available_replicas or 0,
            "replicas": item.spec.replicas or 0,
            "labels": _metadata_map(getattr(item.metadata, "labels", None)),
        }
        for item in deployments
    ]
    statefulset_rows = [
        {
            "name": item.metadata.name,
            "ready_replicas": item.status.ready_replicas or 0,
            "replicas": item.spec.replicas or 0,
            "service_name": item.spec.service_name,
            "labels": _metadata_map(getattr(item.metadata, "labels", None)),
        }
        for item in statefulsets
    ]
    service_rows = [
        {
            "name": item.metadata.name,
            "type": item.spec.type,
            "cluster_ip": item.spec.cluster_ip,
            "ports": _service_ports(item),
            "labels": _metadata_map(getattr(item.metadata, "labels", None)),
        }
        for item in services
    ]
    cluster_summary = {
        "namespace": namespace,
        "limit": limit,
        "node_count": len(node_rows),
        "ready_node_count": ready_node_count,
        "unschedulable_node_count": unschedulable_node_count,
        "storage_class_count": len(storage_class_rows),
        "persistent_volume_count": len(persistent_volume_rows),
        "persistent_volume_claim_count": len(persistent_volume_claim_rows),
        "pod_count": len(pod_rows),
        "deployment_count": len(deployment_rows),
        "statefulset_count": len(statefulset_rows),
        "service_count": len(service_rows),
        "capacity": _resource_totals(capacity_rows),
        "allocatable": _resource_totals(allocatable_rows),
    }

    return ClusterInventoryResult(
        collected_at=_now(),
        namespace=namespace,
        limit=limit,
        node_count=len(node_rows),
        ready_node_count=ready_node_count,
        storage_class_count=len(storage_class_rows),
        persistent_volume_count=len(persistent_volume_rows),
        persistent_volume_claim_count=len(persistent_volume_claim_rows),
        pod_count=len(pod_rows),
        deployment_count=len(deployment_rows),
        statefulset_count=len(statefulset_rows),
        service_count=len(service_rows),
        cluster_summary=cluster_summary,
        report=_build_inventory_report(namespace=namespace, limit=limit, summary=cluster_summary),
        nodes=node_rows,
        storage_classes=storage_class_rows,
        persistent_volumes=persistent_volume_rows,
        persistent_volume_claims=persistent_volume_claim_rows,
        pods=pod_rows,
        deployments=deployment_rows,
        statefulsets=statefulset_rows,
        services=service_rows,
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
