"""Shared communication routing, contract, and operation helpers."""

from __future__ import annotations

from typing import Any

DESTINATION_TYPES = {
    "servicenow",
    "jira",
    "github",
    "pagerduty",
    "rackspace_core",
    "teams",
    "discord",
}

ROUTE_KIND_TICKETING = "ticketing"
ROUTE_KIND_NOTIFICATION = "notification"

TICKET_CAPABLE_DESTINATION_TYPES = {
    "servicenow",
    "jira",
    "github",
    "pagerduty",
    "rackspace_core",
}

CANONICAL_COMMUNICATION_OPERATIONS = {
    "open",
    "notify",
    "update",
    "close",
}

LEGACY_COMMUNICATION_OPERATION_ALIASES = {
    "ticket_create": "open",
    "ticket_comment": "notify",
    "ticket_update": "update",
    "ticket_close": "close",
}

CANONICAL_TO_BAKERY_ACTION = {
    "open": "create",
    "notify": "comment",
    "update": "update",
    "close": "close",
}

RUN_CONDITIONS = {
    "always",
    "remediation_failed",
    "clear_timeout_expired",
    "resolved_after_success",
    "resolved_after_failure",
    "resolved_after_no_remediation",
    "resolved_after_timeout",
}

RUN_PHASES = {
    "firing",
    "escalation",
    "resolving",
    "both",
}

LEGACY_DESTINATION_TYPE_ALIASES = {
    "core": "rackspace_core",
}

ROUTE_PROVIDER_CONFIG_REQUIRED_FIELDS = {
    "rackspace_core": {"account_number"},
    "servicenow": set(),
    "jira": {"project_key"},
    "github": {"owner", "repo"},
    "pagerduty": {"service_id", "from_email"},
    "teams": set(),
    "discord": set(),
}

ROUTE_PROVIDER_CONFIG_ALLOWED_FIELDS = {
    "rackspace_core": {"account_number", "queue", "subcategory", "source", "visibility"},
    "servicenow": {"urgency", "impact"},
    "jira": {"project_key", "issue_type", "transition_id"},
    "github": {"owner", "repo", "labels", "assignees"},
    "pagerduty": {"service_id", "from_email", "urgency"},
    "teams": set(),
    "discord": set(),
}

ALERTMANAGER_REQUIRED_LABEL_FIELDS = {
    "alertname",
    "group_name",
    "severity",
}

ALERTMANAGER_REQUIRED_ANNOTATION_FIELDS = {
    "summary",
    "description",
}

ALERTMANAGER_OPTIONAL_LABEL_FIELDS = {
    "instance",
    "service",
    "team",
    "environment",
    "cluster",
    "namespace",
    "job",
    "region",
}

ALERTMANAGER_OPTIONAL_ANNOTATION_FIELDS = {
    "runbook_url",
    "dashboard_url",
    "playbook_url",
    "investigation_url",
    "silence_url",
    "customer_impact",
    "suggested_action",
}


def normalize_destination_type(value: str | None) -> str:
    raw = str(value or "").strip().lower()
    return LEGACY_DESTINATION_TYPE_ALIASES.get(raw, raw)


def normalize_destination_target(value: Any) -> str:
    return str(value or "").strip()


def _normalize_csv_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    text = str(value).strip()
    return [text] if text else []


def _normalize_provider_config_value(key: str, value: Any) -> Any:
    if key in {"labels", "assignees"}:
        values = _normalize_csv_list(value)
        return values
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip()
    return text or None


def route_provider_config_required_fields(execution_target: str | None) -> set[str]:
    return ROUTE_PROVIDER_CONFIG_REQUIRED_FIELDS.get(
        normalize_destination_type(execution_target), set()
    )


def route_provider_config_allowed_fields(execution_target: str | None) -> set[str]:
    return ROUTE_PROVIDER_CONFIG_ALLOWED_FIELDS.get(
        normalize_destination_type(execution_target), set()
    )


def normalize_route_provider_config(
    execution_target: str | None,
    provider_config: dict[str, Any] | None,
    *,
    require_required: bool = True,
) -> dict[str, Any]:
    target = normalize_destination_type(execution_target)
    raw = provider_config if isinstance(provider_config, dict) else {}
    allowed = route_provider_config_allowed_fields(target)
    if target and target in DESTINATION_TYPES and not allowed and raw:
        raise ValueError(f"{target} routes do not accept provider_config fields")

    normalized: dict[str, Any] = {}
    for key, value in raw.items():
        if key not in allowed:
            raise ValueError(
                f"provider_config.{key} is not supported for execution_target={target or 'unknown'}"
            )
        normalized_value = _normalize_provider_config_value(key, value)
        if normalized_value in (None, [], ""):
            continue
        normalized[key] = normalized_value

    if require_required:
        missing = sorted(
            field
            for field in route_provider_config_required_fields(target)
            if field not in normalized
        )
        if missing:
            joined = ", ".join(missing)
            raise ValueError(f"{target} provider_config requires: {joined}")
    return normalized


def normalize_communication_operation(value: Any) -> str:
    raw = str(value or "").strip().lower()
    if raw in CANONICAL_COMMUNICATION_OPERATIONS:
        return raw
    return LEGACY_COMMUNICATION_OPERATION_ALIASES.get(raw, raw)


def normalize_run_phase(value: str | None) -> str:
    return str(value or "both").strip().lower() or "both"


def normalize_run_condition(value: str | None) -> str:
    return str(value or "always").strip().lower() or "always"


def is_ticket_capable_destination(value: str | None) -> bool:
    return normalize_destination_type(value) in TICKET_CAPABLE_DESTINATION_TYPES


def route_kind_for_destination(value: str | None) -> str:
    if is_ticket_capable_destination(value):
        return ROUTE_KIND_TICKETING
    return ROUTE_KIND_NOTIFICATION


def gates_incident_close_for_destination(value: str | None) -> bool:
    return is_ticket_capable_destination(value)


def canonical_to_bakery_action(value: Any) -> str:
    normalized = normalize_communication_operation(value)
    return CANONICAL_TO_BAKERY_ACTION.get(normalized, normalized)
