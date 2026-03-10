"""Shared communication routing and operation helpers."""

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


def normalize_destination_type(value: str | None) -> str:
    raw = str(value or "").strip().lower()
    return LEGACY_DESTINATION_TYPE_ALIASES.get(raw, raw)


def normalize_destination_target(value: Any) -> str:
    return str(value or "").strip()


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


def canonical_to_bakery_action(value: Any) -> str:
    normalized = normalize_communication_operation(value)
    return CANONICAL_TO_BAKERY_ACTION.get(normalized, normalized)
