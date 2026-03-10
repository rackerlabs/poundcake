"""Bakery execution adapter using PoundCake Bakery client."""

from __future__ import annotations

import hashlib
from typing import Any

from api.core.logging import get_logger
from api.services.communications import (
    canonical_to_bakery_action,
    is_ticket_capable_destination,
    normalize_communication_operation,
)
from api.services.bakery_client import (
    add_ticket_comment_with_key,
    close_ticket_with_key,
    create_ticket_with_key,
    poll_operation,
    update_ticket_with_key,
)
from api.services.execution_adapters.base import ExecutionAdapter
from api.services.execution_types import ExecutionContext, ExecutionResult
from api.validation.execution import validate_bakery_target_payload

logger = get_logger(__name__)


def _deterministic_idempotency_key(
    *,
    order_id: int | None,
    recipe_ingredient_id: int | None,
    action: str,
) -> str | None:
    if order_id is None or recipe_ingredient_id is None:
        return None
    seed = f"resolve:{order_id}:{recipe_ingredient_id}:{action}"
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()


def _coerce_optional_int(value: Any) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


class BakeryExecutionAdapter(ExecutionAdapter):
    engine = "bakery"

    @staticmethod
    def _payload_comment(payload: dict[str, Any]) -> str:
        for key in ("comment", "message", "description", "title"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return "PoundCake updated an existing communication route."

    @staticmethod
    def _reopen_payload(target: str) -> dict[str, Any]:
        if target == "rackspace_core":
            return {"context": {"attributes": {"status": "New"}}}
        return {"state": "open"}

    def validate(self, ctx: ExecutionContext) -> str | None:
        payload = ctx.execution_payload if isinstance(ctx.execution_payload, dict) else {}
        parameters = ctx.execution_parameters if isinstance(ctx.execution_parameters, dict) else {}
        ticket_id = str(
            payload.get("ticket_id")
            or ctx.context.get("ticket_id")
            or ctx.context.get("bakery_ticket_id")
            or ""
        ).strip()
        return validate_bakery_target_payload(
            execution_target=ctx.execution_target,
            payload=payload,
            execution_parameters=parameters,
            bakery_ticket_id=ticket_id or None,
        )

    async def execute_once(self, ctx: ExecutionContext) -> ExecutionResult:
        payload = ctx.execution_payload if isinstance(ctx.execution_payload, dict) else {}
        target = (ctx.execution_target or "").strip().lower()
        parameters = ctx.execution_parameters if isinstance(ctx.execution_parameters, dict) else {}
        operation = normalize_communication_operation(parameters.get("operation"))
        bakery_action = canonical_to_bakery_action(operation)

        order_id = _coerce_optional_int(ctx.context.get("order_id"))
        recipe_ingredient_id = _coerce_optional_int(ctx.context.get("recipe_ingredient_id"))
        idem_key = _deterministic_idempotency_key(
            order_id=order_id,
            recipe_ingredient_id=recipe_ingredient_id,
            action=operation or target,
        )

        ticket_id = str(
            payload.get("ticket_id")
            or ctx.context.get("ticket_id")
            or ctx.context.get("bakery_ticket_id")
            or ""
        ).strip()

        try:
            accepted: dict[str, Any]
            context_updates: dict[str, Any] = {}
            if operation == "open":
                reuse_mode = str(ctx.context.get("communication_reuse_mode") or "").strip().lower()
                if ticket_id and is_ticket_capable_destination(target):
                    if reuse_mode == "reopen":
                        await update_ticket_with_key(
                            req_id=ctx.req_id,
                            ticket_id=ticket_id,
                            payload=self._reopen_payload(target),
                            idempotency_key=idem_key,
                        )
                    accepted = await add_ticket_comment_with_key(
                        req_id=ctx.req_id,
                        ticket_id=ticket_id,
                        payload={"comment": self._payload_comment(payload)},
                        idempotency_key=idem_key,
                    )
                else:
                    accepted = await create_ticket_with_key(
                        req_id=ctx.req_id,
                        payload=payload,
                        idempotency_key=idem_key,
                    )
                    created_ticket_id = str(accepted.get("ticket_id") or "").strip()
                    if created_ticket_id:
                        context_updates["bakery_ticket_id"] = created_ticket_id
                        ticket_id = created_ticket_id
            elif operation == "update":
                accepted = await update_ticket_with_key(
                    req_id=ctx.req_id,
                    ticket_id=ticket_id,
                    payload=payload,
                    idempotency_key=idem_key,
                )
            elif operation == "notify":
                comment_payload = payload if "comment" in payload else {"comment": self._payload_comment(payload)}
                accepted = await add_ticket_comment_with_key(
                    req_id=ctx.req_id,
                    ticket_id=ticket_id,
                    payload=comment_payload,
                    idempotency_key=idem_key,
                )
            elif operation == "close":
                accepted = await close_ticket_with_key(
                    req_id=ctx.req_id,
                    ticket_id=ticket_id,
                    payload=payload,
                    idempotency_key=idem_key,
                )
            elif bakery_action == "create":
                accepted = await create_ticket_with_key(
                    req_id=ctx.req_id,
                    payload=payload,
                    idempotency_key=idem_key,
                )
                created_ticket_id = str(accepted.get("ticket_id") or "").strip()
                if created_ticket_id:
                    context_updates["bakery_ticket_id"] = created_ticket_id
                    ticket_id = created_ticket_id
            elif bakery_action == "update":
                accepted = await update_ticket_with_key(
                    req_id=ctx.req_id,
                    ticket_id=ticket_id,
                    payload=payload,
                    idempotency_key=idem_key,
                )
            elif bakery_action == "comment":
                comment_payload = payload if "comment" in payload else {"comment": str(payload)}
                accepted = await add_ticket_comment_with_key(
                    req_id=ctx.req_id,
                    ticket_id=ticket_id,
                    payload=comment_payload,
                    idempotency_key=idem_key,
                )
            elif bakery_action == "close":
                accepted = await close_ticket_with_key(
                    req_id=ctx.req_id,
                    ticket_id=ticket_id,
                    payload=payload,
                    idempotency_key=idem_key,
                )
            else:
                return ExecutionResult(
                    engine=self.engine,
                    status="failed",
                    error_message=(
                        "Unsupported bakery operation. "
                        "Expected execution_parameters.operation to be one of: "
                        "open, notify, update, close, "
                        "ticket_create, ticket_update, ticket_comment, ticket_close"
                    ),
                    retryable=False,
                )

            execution_ref = (
                str(
                    accepted.get("operation_id")
                    or accepted.get("request_id")
                    or accepted.get("id")
                    or ""
                )
                or None
            )

            terminal_payload: dict[str, Any] = accepted
            operation_id = accepted.get("operation_id")
            if operation_id:
                terminal_payload = await poll_operation(str(operation_id))

            terminal_status = str(terminal_payload.get("status") or "").lower()
            if terminal_status in {"succeeded", "success", "completed"}:
                return ExecutionResult(
                    engine=self.engine,
                    status="succeeded",
                    execution_ref=execution_ref,
                    result=terminal_payload,
                    raw=terminal_payload,
                    context_updates=context_updates,
                )

            error_message = str(
                terminal_payload.get("last_error")
                or terminal_payload.get("error")
                or f"Bakery operation terminal status={terminal_status or 'unknown'}"
            )
            return ExecutionResult(
                engine=self.engine,
                status="failed",
                execution_ref=execution_ref,
                error_message=error_message,
                result=terminal_payload,
                raw=terminal_payload,
                retryable=False,
                context_updates=context_updates,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "Bakery execution attempt failed",
                extra={
                    "req_id": ctx.req_id,
                    "target": ctx.execution_target,
                    "error": str(exc),
                },
            )
            return ExecutionResult(
                engine=self.engine,
                status="failed",
                error_message=str(exc),
                retryable=True,
            )
