"""StackStorm execution adapter."""

from __future__ import annotations

from typing import Any

from api.core.logging import get_logger
from api.services.execution_adapters.base import ExecutionAdapter
from api.services.execution_types import CanonicalExecutionStatus, ExecutionContext, ExecutionResult
from api.services.stackstorm_service import StackStormActionManager, StackStormError
from api.validation.execution import validate_stackstorm_execution_request

logger = get_logger(__name__)


def _map_stackstorm_status(raw_status: str) -> CanonicalExecutionStatus:
    status = (raw_status or "").strip().lower()
    if status in {"requested", "scheduled", "pending", "pausing", "resuming"}:
        return "queued"
    if status in {"running"}:
        return "running"
    if status in {"succeeded"}:
        return "succeeded"
    if status in {"canceled", "canceling"}:
        return "canceled"
    return "failed"


class StackStormExecutionAdapter(ExecutionAdapter):
    engine = "stackstorm"

    def __init__(self, manager: StackStormActionManager) -> None:
        self._manager = manager

    def validate(self, ctx: ExecutionContext) -> str | None:
        return validate_stackstorm_execution_request(
            execution_target=ctx.execution_target,
            execution_payload=ctx.execution_payload,
            execution_parameters=ctx.execution_parameters,
        )

    async def execute_once(self, ctx: ExecutionContext) -> ExecutionResult:
        try:
            payload: dict[str, Any] = ctx.execution_parameters or {}
            raw = await self._manager._client.execute_action(
                req_id=ctx.req_id,
                action_ref=ctx.execution_target,
                parameters=payload,
                timeout=ctx.timeout_duration_sec,
            )
            mapped_status = _map_stackstorm_status(str(raw.get("status") or ""))
            return ExecutionResult(
                engine=self.engine,
                status=mapped_status,
                execution_ref=str(raw.get("id") or "") or None,
                result=raw.get("result") if isinstance(raw.get("result"), dict) else None,
                raw=raw,
            )
        except StackStormError as exc:
            logger.warning(
                "StackStorm execution attempt failed",
                extra={"req_id": ctx.req_id, "target": ctx.execution_target, "error": str(exc)},
            )
            return ExecutionResult(
                engine=self.engine,
                status="failed",
                error_message=str(exc),
                retryable=True,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "StackStorm adapter unexpected failure",
                extra={"req_id": ctx.req_id, "target": ctx.execution_target, "error": str(exc)},
            )
            return ExecutionResult(
                engine=self.engine,
                status="failed",
                error_message=str(exc),
                retryable=False,
            )
