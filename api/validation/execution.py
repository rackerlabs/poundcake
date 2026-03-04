"""Execution payload validation helpers."""

from __future__ import annotations

from typing import Any

from api.services.execution_types import SUPPORTED_EXECUTION_ENGINES


def normalize_execution_engine(execution_engine: str | None) -> str:
    return (execution_engine or "").strip().lower()


def validate_execution_common(
    *,
    execution_engine: str | None,
    execution_target: str | None,
    execution_payload: dict[str, Any] | None,
    execution_parameters: dict[str, Any] | None,
) -> str | None:
    engine = normalize_execution_engine(execution_engine)
    if engine not in SUPPORTED_EXECUTION_ENGINES:
        return "execution_engine must be one of: " + ", ".join(sorted(SUPPORTED_EXECUTION_ENGINES))

    if not isinstance(execution_target, str) or not execution_target.strip():
        return "execution_target is required"

    if execution_payload is not None and not isinstance(execution_payload, dict):
        return "execution_payload must be an object when provided"

    if execution_parameters is not None and not isinstance(execution_parameters, dict):
        return "execution_parameters must be an object when provided"

    return None


def validate_stackstorm_execution_request(
    *,
    execution_target: str | None,
    execution_payload: dict[str, Any] | None,
    execution_parameters: dict[str, Any] | None,
) -> str | None:
    if not isinstance(execution_target, str) or not execution_target.strip():
        return "stackstorm execution_target is required"
    if execution_payload is not None and not isinstance(execution_payload, dict):
        return "execution_payload must be an object when provided"
    if execution_parameters is not None and not isinstance(execution_parameters, dict):
        return "execution_parameters must be an object when provided"
    return None


def validate_bakery_target_payload(
    *,
    execution_target: str,
    payload: dict[str, Any],
    execution_parameters: dict[str, Any] | None = None,
    bakery_ticket_id: str | None = None,
) -> str | None:
    target = execution_target.lower()
    ticket_id = str(payload.get("ticket_id") or bakery_ticket_id or "").strip()
    params = execution_parameters if isinstance(execution_parameters, dict) else {}
    operation = str(params.get("operation") or "").strip().lower()

    if target not in {"core", "jira"}:
        return "bakery execution_target must be one of: core, jira"

    if operation not in {"ticket_create", "ticket_update", "ticket_comment", "ticket_close"}:
        return (
            "bakery execution_parameters.operation must be one of: "
            "ticket_create, ticket_update, ticket_comment, ticket_close"
        )

    if operation == "ticket_create":
        if not isinstance(payload.get("title"), str) or not payload.get("title"):
            return "ticket_create requires payload.title"
        if not isinstance(payload.get("description"), str) or not payload.get("description"):
            return "ticket_create requires payload.description"
        return None

    if operation == "ticket_update":
        if not ticket_id:
            return "ticket_update requires payload.ticket_id or bakery_ticket_id"
        return None

    if operation == "ticket_comment":
        if not ticket_id:
            return "ticket_comment requires payload.ticket_id or bakery_ticket_id"
        if not isinstance(payload.get("comment"), str) or not payload.get("comment"):
            return "ticket_comment requires payload.comment"
        return None

    if operation == "ticket_close":
        if not ticket_id:
            return "ticket_close requires payload.ticket_id or bakery_ticket_id"
        return None

    return None


def validate_execution_request(
    *,
    execution_engine: str | None,
    execution_target: str | None,
    execution_payload: dict[str, Any] | None,
    execution_parameters: dict[str, Any] | None,
    context: dict[str, Any] | None = None,
) -> str | None:
    error = validate_execution_common(
        execution_engine=execution_engine,
        execution_target=execution_target,
        execution_payload=execution_payload,
        execution_parameters=execution_parameters,
    )
    if error:
        return error

    engine = normalize_execution_engine(execution_engine)
    if engine == "stackstorm":
        return validate_stackstorm_execution_request(
            execution_target=execution_target,
            execution_payload=execution_payload,
            execution_parameters=execution_parameters,
        )
    if engine == "bakery":
        payload = execution_payload if isinstance(execution_payload, dict) else {}
        context_data = context if isinstance(context, dict) else {}
        ticket_id = str(context_data.get("ticket_id") or context_data.get("bakery_ticket_id") or "")
        return validate_bakery_target_payload(
            execution_target=str(execution_target),
            payload=payload,
            execution_parameters=execution_parameters,
            bakery_ticket_id=ticket_id or None,
        )
    return None


def validate_runtime_execution_payload(
    *,
    execution_engine: str | None,
    execution_purpose: str | None,
    execution_target: str | None,
    execution_payload: dict[str, Any] | None,
    execution_parameters: dict[str, Any] | None = None,
) -> str | None:
    """Validate engine-aware execution payload contract for runtime orchestration."""
    if execution_payload is not None and not isinstance(execution_payload, dict):
        return "execution_payload must be an object when provided"

    if (execution_purpose or "").lower() != "comms":
        return None
    if normalize_execution_engine(execution_engine) != "bakery":
        return "comms ingredients must use execution_engine='bakery'"

    target = (execution_target or "").lower()
    if target not in {"core", "jira"}:
        return "bakery comms ingredient execution_target must be one of: " "core, jira"
    params = execution_parameters if isinstance(execution_parameters, dict) else {}
    operation = str(params.get("operation") or "").strip().lower()
    if operation not in {"ticket_create", "ticket_update", "ticket_comment", "ticket_close"}:
        return (
            "bakery comms ingredient execution_parameters.operation must be one of: "
            "ticket_create, ticket_update, ticket_comment, ticket_close"
        )

    if execution_payload is None:
        return "bakery comms ingredient requires execution_payload"
    template = execution_payload.get("template")
    if not isinstance(template, dict):
        return "bakery comms ingredient execution_payload.template must be an object"
    return None
