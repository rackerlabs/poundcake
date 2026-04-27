"""Canonical communication envelope construction for Bakery-bound executions."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from api.models.models import DishIngredient, Order
from api.services.communications import (
    DESTINATION_TYPES,
    normalize_destination_target,
    normalize_destination_type,
)
from api.services.communications_policy import POLICY_METADATA_KEY

KNOWN_LINK_FIELDS = (
    ("runbook_url", "Runbook"),
    ("dashboard_url", "Dashboard"),
    ("playbook_url", "Playbook"),
    ("investigation_url", "Investigation"),
    ("silence_url", "Silence"),
)
NODE_LABEL_FIELDS = (
    "affected_node",
    "node",
    "k8s_node_name",
    "host_name",
    "node_hostname",
    "hostname",
    "host",
    "service_instance_id",
    "instance",
)
DEVICE_NUMBER_LABEL_FIELDS = (
    "device_number",
    "device_id",
    "computer_number",
    "computer_id",
    "core_device_number",
    "core_device_id",
    "rackspace_device_number",
    "rackspace_device_id",
    "rackspace_com_device_number",
    "rackspace_com_device_id",
    "server_number",
)
DEVICE_NAME_LABEL_FIELDS = (
    "affected_device",
    "device_name",
    "device",
    *NODE_LABEL_FIELDS,
)
RESULT_TEXT_PRIORITY = (
    "stdout",
    "stderr",
    "message",
    "messages",
    "output",
    "outputs",
    "detail",
    "details",
    "summary",
    "body",
    "content",
    "response",
    "result",
    "results",
)
CANONICAL_OUTCOME_LIMIT = 240


def _iso(value: Any) -> str | None:
    if isinstance(value, datetime):
        return value.isoformat()
    if value in (None, ""):
        return None
    return str(value)


def _first_text(*values: Any) -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _collapse_line(value: Any) -> str:
    if value is None:
        return ""
    return " ".join(str(value).split()).strip()


def _normalize_multiline_text(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    lines = [line.strip() for line in value.replace("\r\n", "\n").split("\n")]
    normalized: list[str] = []
    pending_blank = False
    for line in lines:
        if line:
            normalized.append(line)
            pending_blank = False
            continue
        if normalized and not pending_blank:
            normalized.append("")
            pending_blank = True
    return "\n".join(normalized).strip()


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    if limit <= 3:
        return text[:limit]
    return text[: limit - 3].rstrip() + "..."


def _affected_node_from_labels(labels: dict[str, Any]) -> str:
    return _first_text(*(labels.get(key) for key in NODE_LABEL_FIELDS))


def _device_context_from_labels(labels: dict[str, Any]) -> dict[str, Any]:
    name = ""
    source_label = ""
    for key in DEVICE_NAME_LABEL_FIELDS:
        value = _collapse_line(labels.get(key))
        if value:
            name = value
            source_label = key
            break

    number = _first_text(*(labels.get(key) for key in DEVICE_NUMBER_LABEL_FIELDS))
    if not number and name:
        match = re.match(r"^(\d+)(?:[-_.].*)?$", name)
        if match:
            number = match.group(1)

    if not name and not number:
        return {}

    return {
        "name": name,
        "hostname": name,
        "number": number,
        "source_label": source_label,
    }


def _result_scalar_lines(value: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    for key, item in value.items():
        if key in RESULT_TEXT_PRIORITY:
            continue
        if isinstance(item, (str, int, float, bool)):
            text = _collapse_line(item)
            if text:
                lines.append(f"{key}: {text}")
        if len(lines) >= 4:
            break
    return lines


def _extract_result_excerpt(value: Any, *, depth: int = 0) -> str:
    if depth > 4 or value is None:
        return ""
    if isinstance(value, str):
        return _normalize_multiline_text(value)
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, list):
        lines: list[str] = []
        for item in value[:4]:
            excerpt = _extract_result_excerpt(item, depth=depth + 1)
            if excerpt:
                lines.append(excerpt)
        return "\n".join(line for line in lines if line).strip()
    if not isinstance(value, dict):
        return ""

    stream_lines: list[str] = []
    for key, label in (("stdout", "stdout"), ("stderr", "stderr")):
        excerpt = _extract_result_excerpt(value.get(key), depth=depth + 1)
        if excerpt:
            stream_lines.append(f"{label}:\n{excerpt}")
    if stream_lines:
        return "\n\n".join(stream_lines).strip()

    for key in RESULT_TEXT_PRIORITY:
        excerpt = _extract_result_excerpt(value.get(key), depth=depth + 1)
        if excerpt:
            return excerpt

    scalar_lines = _result_scalar_lines(value)
    if scalar_lines:
        return "\n".join(scalar_lines)

    for item in value.values():
        excerpt = _extract_result_excerpt(item, depth=depth + 1)
        if excerpt:
            return excerpt
    return ""


def _normalize_step_status(value: Any) -> str:
    normalized = _collapse_line(value).lower().replace(" ", "_")
    if normalized in {
        "",
        "pending",
        "new",
        "queued",
        "requested",
        "scheduled",
        "running",
        "processing",
    }:
        return "incomplete" if normalized else ""
    if normalized in {"succeeded", "success", "successful", "completed", "complete"}:
        return "succeeded"
    if normalized in {"failed", "failure", "error", "abandoned", "timed_out", "timeout"}:
        return "failed"
    if normalized in {"skipped", "canceled", "cancelled"}:
        return "skipped"
    return normalized


def _display_status(value: Any) -> str:
    status = _normalize_step_status(value)
    if not status:
        return ""
    if status == "incomplete":
        return "in progress"
    return status.replace("_", " ")


def _step_sort_key(step: DishIngredient) -> tuple[str, str, int]:
    started = _iso(step.started_at) or _iso(step.created_at) or ""
    completed = _iso(step.completed_at) or ""
    return (started, completed, int(getattr(step, "id", 0) or 0))


def _step_label(step: DishIngredient) -> str:
    return _first_text(
        step.task_key,
        (
            getattr(getattr(step, "recipe_ingredient", None), "ingredient", None).task_key_template
            if getattr(getattr(step, "recipe_ingredient", None), "ingredient", None) is not None
            else None
        ),
        step.execution_target,
        f"step-{getattr(step, 'id', 'unknown')}",
    )


def _is_communication_step(step: DishIngredient) -> bool:
    recipe_ingredient = getattr(step, "recipe_ingredient", None)
    ingredient = getattr(recipe_ingredient, "ingredient", None)
    purpose = _collapse_line(getattr(ingredient, "execution_purpose", "")).lower()
    if purpose:
        return purpose == "comms"
    engine = _collapse_line(step.execution_engine).lower()
    target = normalize_destination_type(_collapse_line(step.execution_target))
    return engine == "bakery" and target in DESTINATION_TYPES


def _step_excerpt(step: DishIngredient) -> str:
    result_excerpt = _extract_result_excerpt(step.result)
    error_excerpt = _normalize_multiline_text(step.error_message)
    if error_excerpt and result_excerpt and error_excerpt not in result_excerpt:
        return f"{error_excerpt}\n\n{result_excerpt}"
    return error_excerpt or result_excerpt


def _step_outcome(step: DishIngredient) -> str:
    excerpt = _step_excerpt(step)
    if excerpt:
        return _truncate(_collapse_line(excerpt), CANONICAL_OUTCOME_LIMIT)
    return _display_status(step.execution_status)


def _build_remediation_context(order: Order) -> dict[str, Any]:
    steps = sorted(
        [
            step
            for dish in (order.dishes or [])
            for step in (dish.dish_ingredients or [])
            if not getattr(step, "deleted", False) and not _is_communication_step(step)
        ],
        key=_step_sort_key,
    )

    counts = {"total": len(steps), "succeeded": 0, "failed": 0, "skipped": 0, "incomplete": 0}
    before_excerpt = ""
    after_excerpt = ""
    failure_excerpt = ""
    latest_completed_step: dict[str, Any] | None = None
    step_rows: list[dict[str, Any]] = []

    for step in steps:
        status = _normalize_step_status(step.execution_status)
        if status == "succeeded":
            counts["succeeded"] += 1
            latest_completed_step = {
                "task_key": _step_label(step),
                "status": status,
                "outcome": _step_outcome(step),
                "started_at": _iso(step.started_at),
                "completed_at": _iso(step.completed_at),
                "execution_ref": _first_text(step.execution_ref),
            }
        elif status == "failed":
            counts["failed"] += 1
        elif status == "skipped":
            counts["skipped"] += 1
        else:
            counts["incomplete"] += 1

        excerpt = _step_excerpt(step)
        if excerpt and not before_excerpt:
            before_excerpt = excerpt
        if excerpt:
            after_excerpt = excerpt
        if status == "failed" and excerpt:
            failure_excerpt = excerpt

        step_rows.append(
            {
                "task_key": _step_label(step),
                "status": status or _collapse_line(step.execution_status).lower(),
                "started_at": _iso(step.started_at),
                "completed_at": _iso(step.completed_at),
                "execution_ref": _first_text(step.execution_ref),
                "outcome": _step_outcome(step),
            }
        )

    remediation_outcome = _collapse_line(order.remediation_outcome).lower()
    if remediation_outcome != "succeeded":
        after_excerpt = ""

    return {
        "summary": counts,
        "steps": step_rows,
        "before_excerpt": before_excerpt,
        "after_excerpt": after_excerpt,
        "failure_excerpt": failure_excerpt,
        "latest_completed_step": latest_completed_step,
    }


def _build_correlation_context(order: Order) -> dict[str, Any]:
    labels = dict(order.labels or {})
    raw_data = dict(order.raw_data or {})
    stored = raw_data.get("correlation") if isinstance(raw_data.get("correlation"), dict) else {}
    children = [child for child in stored.get("children", []) if isinstance(child, dict)]
    affected_node = _affected_node_from_labels(labels)
    raw_affected_nodes = (
        stored.get("affected_nodes") if isinstance(stored.get("affected_nodes"), list) else []
    )
    affected_nodes = [str(item).strip() for item in raw_affected_nodes if str(item or "").strip()]
    if affected_node and affected_node not in affected_nodes:
        affected_nodes.append(affected_node)
    return {
        "scope": _first_text(labels.get("correlation_scope"), stored.get("scope")),
        "key": _first_text(labels.get("correlation_key"), stored.get("key")),
        "affected_node": affected_node,
        "root_cause": _first_text(labels.get("root_cause")).lower() == "true",
        "child_count": int(stored.get("child_count") or len(children)),
        "active_child_count": int(
            stored.get("active_child_count")
            if stored.get("active_child_count") is not None
            else len([child for child in children if child.get("status") != "resolved"])
        ),
        "child_counts_by_group": stored.get("child_counts_by_group") or {},
        "affected_namespaces": stored.get("affected_namespaces") or [],
        "affected_workloads": stored.get("affected_workloads") or [],
        "affected_nodes": affected_nodes,
        "children": children[:25],
    }


def _format_correlation_summary(correlation: dict[str, Any]) -> str:
    if not correlation.get("root_cause") or int(correlation.get("child_count") or 0) <= 0:
        return ""
    parts = [
        "Correlated child alerts: "
        f"{correlation.get('child_count')} total, {correlation.get('active_child_count')} active."
    ]
    namespaces = [str(item) for item in correlation.get("affected_namespaces") or [] if item]
    if namespaces:
        parts.append(
            "Namespaces: " + ", ".join(namespaces[:10]) + (" ..." if len(namespaces) > 10 else "")
        )
    workloads = [str(item) for item in correlation.get("affected_workloads") or [] if item]
    if workloads:
        parts.append(
            "Workloads: " + ", ".join(workloads[:10]) + (" ..." if len(workloads) > 10 else "")
        )
    counts = correlation.get("child_counts_by_group") or {}
    if isinstance(counts, dict) and counts:
        rendered = ", ".join(f"{name}={count}" for name, count in sorted(counts.items())[:10])
        parts.append("Alert groups: " + rendered)
    return "\n".join(parts)


def build_canonical_communication_context(
    *,
    order: Order,
    execution_target: str,
    destination_target: str | None,
    operation: str,
    execution_payload: dict[str, Any] | None,
) -> dict[str, Any]:
    payload = execution_payload if isinstance(execution_payload, dict) else {}
    context = payload.get("context") if isinstance(payload.get("context"), dict) else {}
    labels = dict(order.labels or {})
    annotations = dict(order.annotations or {})
    raw_data = dict(order.raw_data or {})
    metadata = (
        context.get(POLICY_METADATA_KEY)
        if isinstance(context.get(POLICY_METADATA_KEY), dict)
        else {}
    )
    semantic_text = (
        context.get("semantic_text") if isinstance(context.get("semantic_text"), dict) else {}
    )
    provider_config = (
        context.get("provider_config") if isinstance(context.get("provider_config"), dict) else {}
    )

    links: list[dict[str, str]] = []
    generator_url = _first_text(raw_data.get("generatorURL"))
    if generator_url:
        links.append({"label": "Source", "url": generator_url})
    for key, label in KNOWN_LINK_FIELDS:
        url = _first_text(annotations.get(key))
        if url:
            links.append({"label": label, "url": url})

    correlation = _build_correlation_context(order)
    device = _device_context_from_labels(labels)
    alert_instance = _first_text(
        device.get("name"),
        correlation.get("affected_node"),
        order.instance,
        labels.get("instance"),
    )
    detail = _first_text(
        semantic_text.get("detail"),
        payload.get("message"),
        payload.get("comment"),
        payload.get("resolution_notes"),
        annotations.get("description"),
    )
    correlation_summary = _format_correlation_summary(correlation)
    if correlation_summary:
        detail = f"{detail}\n\n{correlation_summary}" if detail else correlation_summary

    return {
        "schema_version": 1,
        "event": {
            "name": _first_text(metadata.get("event")),
            "operation": operation,
            "managed": bool(metadata.get("managed")),
            "source": _first_text(context.get("source"), payload.get("source"), "poundcake"),
        },
        "route": {
            "id": _first_text(metadata.get("route_id")),
            "label": _first_text(context.get("route_label"), metadata.get("label")),
            "execution_target": normalize_destination_type(execution_target),
            "destination_target": normalize_destination_target(destination_target),
            "provider_config": provider_config,
        },
        "order": {
            "id": order.id,
            "req_id": order.req_id,
            "processing_status": order.processing_status,
            "alert_status": order.alert_status,
            "remediation_outcome": order.remediation_outcome,
            "counter": order.counter,
            "clear_timeout_sec": order.clear_timeout_sec,
            "clear_deadline_at": _iso(order.clear_deadline_at),
            "clear_timed_out_at": _iso(order.clear_timed_out_at),
            "auto_close_eligible": bool(order.auto_close_eligible),
        },
        "alert": {
            "group_name": order.alert_group_name,
            "severity": _first_text(order.severity, labels.get("severity"), "unknown"),
            "status": _first_text(order.alert_status),
            "fingerprint": _first_text(order.fingerprint),
            "instance": alert_instance,
            "starts_at": _iso(order.starts_at),
            "ends_at": _iso(order.ends_at),
            "labels": labels,
            "annotations": annotations,
            "generator_url": generator_url,
        },
        "device": device,
        "links": links,
        "text": {
            "headline": _first_text(
                semantic_text.get("headline"),
                payload.get("title"),
                annotations.get("summary"),
                order.alert_group_name,
            ),
            "summary": _first_text(
                semantic_text.get("summary"),
                payload.get("description"),
                annotations.get("summary"),
            ),
            "detail": detail,
            "resolution": _first_text(
                semantic_text.get("resolution"),
                payload.get("resolution_notes"),
                payload.get("comment"),
                payload.get("message"),
            ),
        },
        "correlation": correlation,
        "remediation": _build_remediation_context(order),
    }
