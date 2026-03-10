"""Execution payload validation helpers."""

from __future__ import annotations

from typing import Any

from api.services.communications import (
    DESTINATION_TYPES,
    TICKET_CAPABLE_DESTINATION_TYPES,
    normalize_communication_operation,
    normalize_destination_type,
)
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
    target = normalize_destination_type(execution_target)
    ticket_id = str(payload.get("ticket_id") or bakery_ticket_id or "").strip()
    params = execution_parameters if isinstance(execution_parameters, dict) else {}
    operation = normalize_communication_operation(params.get("operation"))

    if target not in DESTINATION_TYPES:
        return "bakery execution_target must be one of: " + ", ".join(sorted(DESTINATION_TYPES))

    if operation not in {"open", "notify", "update", "close"}:
        return (
            "bakery execution_parameters.operation must be one of: "
            "open, notify, update, close, "
            "ticket_create, ticket_update, ticket_comment, ticket_close"
        )

    if operation == "open":
        if target in TICKET_CAPABLE_DESTINATION_TYPES:
            if not isinstance(payload.get("title"), str) or not payload.get("title"):
                return "open requires payload.title for ticket-capable destinations"
            if not isinstance(payload.get("description"), str) or not payload.get("description"):
                return "open requires payload.description for ticket-capable destinations"
        elif not any(
            isinstance(payload.get(key), str) and str(payload.get(key)).strip()
            for key in ("message", "comment", "description", "title")
        ):
            return "open requires a message-style payload for chat destinations"
        return None

    if operation == "update":
        return None

    if operation == "notify":
        if not any(
            isinstance(payload.get(key), str) and str(payload.get(key)).strip()
            for key in ("comment", "message", "description", "title")
        ):
            return "notify requires payload.comment, payload.message, payload.description, or payload.title"
        return None

    if operation == "close":
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

    target = normalize_destination_type(execution_target)
    if target not in DESTINATION_TYPES:
        return "bakery comms ingredient execution_target must be one of: " + ", ".join(
            sorted(DESTINATION_TYPES)
        )
    params = execution_parameters if isinstance(execution_parameters, dict) else {}
    operation = normalize_communication_operation(params.get("operation"))
    if operation not in {"open", "notify", "update", "close"}:
        return (
            "bakery comms ingredient execution_parameters.operation must be one of: "
            "open, notify, update, close, "
            "ticket_create, ticket_update, ticket_comment, ticket_close"
        )

    if execution_payload is None:
        return "bakery comms ingredient requires execution_payload"
    return None
