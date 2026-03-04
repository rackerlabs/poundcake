"""Shared execution orchestration types."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

CanonicalExecutionStatus = Literal["queued", "running", "succeeded", "failed", "canceled"]

TERMINAL_EXECUTION_STATUSES: set[CanonicalExecutionStatus] = {
    "succeeded",
    "failed",
    "canceled",
}

SUPPORTED_EXECUTION_ENGINES = {"stackstorm", "bakery"}


@dataclass(slots=True)
class ExecutionContext:
    engine: str
    execution_target: str
    req_id: str
    execution_payload: dict[str, Any] | None = None
    execution_parameters: dict[str, Any] | None = None
    retry_count: int = 0
    retry_delay: int = 0
    timeout_duration_sec: int = 300
    context: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ExecutionResult:
    engine: str
    status: CanonicalExecutionStatus
    execution_ref: str | None = None
    error_message: str | None = None
    result: dict[str, Any] | None = None
    raw: dict[str, Any] | None = None
    retryable: bool = False
    attempts: int = 1
    context_updates: dict[str, Any] = field(default_factory=dict)
