"""Canonical communication envelope construction for Bakery-bound executions."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from api.models.models import Order
from api.services.communications import normalize_destination_target, normalize_destination_type
from api.services.communications_policy import POLICY_METADATA_KEY

KNOWN_LINK_FIELDS = (
    ("runbook_url", "Runbook"),
    ("dashboard_url", "Dashboard"),
    ("playbook_url", "Playbook"),
    ("investigation_url", "Investigation"),
    ("silence_url", "Silence"),
)


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
            "instance": _first_text(order.instance, labels.get("instance")),
            "starts_at": _iso(order.starts_at),
            "ends_at": _iso(order.ends_at),
            "labels": labels,
            "annotations": annotations,
            "generator_url": generator_url,
        },
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
            "detail": _first_text(
                semantic_text.get("detail"),
                payload.get("message"),
                payload.get("comment"),
                payload.get("resolution_notes"),
                annotations.get("description"),
            ),
            "resolution": _first_text(
                semantic_text.get("resolution"),
                payload.get("resolution_notes"),
                payload.get("comment"),
                payload.get("message"),
            ),
        },
    }
