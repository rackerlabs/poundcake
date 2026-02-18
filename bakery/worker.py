#!/usr/bin/env python3
"""DB-backed worker for Bakery ticket operations."""

from __future__ import annotations

import asyncio
import math
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import structlog
from sqlalchemy import and_, or_

from bakery.config import settings
from bakery.database import SessionLocal
from bakery.metrics import (
    BAKERY_DEAD_LETTER_TOTAL,
    BAKERY_OPERATION_LATENCY_SECONDS,
    BAKERY_OPERATIONS_TOTAL,
    BAKERY_RETRIES_TOTAL,
)
from bakery.mixer.factory import get_mixer
from bakery.models import Ticket, TicketOperation

logger = structlog.get_logger()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _build_provider_payload(
    action: str,
    ticket: Ticket,
    payload: dict[str, Any],
) -> dict[str, Any]:
    provider_extras = payload.get("provider_extras") or {}
    provider_payload = dict(provider_extras)

    if action == "create":
        provider_payload.setdefault("title", payload.get("title", ""))
        provider_payload.setdefault("description", payload.get("description", ""))
        if payload.get("severity") is not None:
            provider_payload.setdefault("severity", payload.get("severity"))
        if payload.get("category") is not None:
            provider_payload.setdefault("category", payload.get("category"))
        if payload.get("source") is not None:
            provider_payload.setdefault("source", payload.get("source"))
        return provider_payload

    if not ticket.provider_ticket_id:
        raise ValueError("Provider ticket id is not available yet for this ticket")
    provider_payload.setdefault("ticket_id", ticket.provider_ticket_id)

    if action == "update":
        updates = provider_payload.get("updates")
        if not updates:
            updates = {}
            for field in ("title", "description", "severity", "category", "state"):
                if payload.get(field) is not None:
                    updates[field] = payload.get(field)
            if updates:
                provider_payload["updates"] = updates
        return provider_payload

    if action == "comment":
        provider_payload.setdefault("comment", payload.get("comment", ""))
        if payload.get("visibility") is not None:
            provider_payload.setdefault("visibility", payload.get("visibility"))
        return provider_payload

    if action == "close":
        if payload.get("resolution_notes") is not None:
            provider_payload.setdefault("close_notes", payload.get("resolution_notes"))
        if payload.get("resolution_code") is not None:
            provider_payload.setdefault("resolution_code", payload.get("resolution_code"))
        if payload.get("state") is not None:
            provider_payload.setdefault("state", payload.get("state"))
        return provider_payload

    raise ValueError(f"Unsupported action: {action}")


def _compute_backoff(attempt: int) -> int:
    raw = settings.worker_backoff_base_sec * int(math.pow(2, max(attempt - 1, 0)))
    return min(raw, settings.worker_backoff_max_sec)


def _claim_operations(batch_size: int) -> list[TicketOperation]:
    now = _now()
    with SessionLocal() as db:
        rows = (
            db.query(TicketOperation)
            .filter(
                and_(
                    TicketOperation.status.in_(["queued", "failed"]),
                    or_(
                        TicketOperation.next_attempt_at.is_(None),
                        TicketOperation.next_attempt_at <= now,
                    ),
                )
            )
            .order_by(TicketOperation.created_at.asc())
            .with_for_update(skip_locked=True)
            .limit(batch_size)
            .all()
        )
        if not rows:
            db.commit()
            return []

        for row in rows:
            row.status = "running"
            row.started_at = now
            row.updated_at = now
        db.commit()
        for row in rows:
            db.refresh(row)
        return rows


def _load_ticket(internal_ticket_id: str) -> Ticket:
    with SessionLocal() as db:
        ticket = db.query(Ticket).filter(Ticket.internal_ticket_id == internal_ticket_id).first()
        if not ticket:
            raise ValueError("Ticket does not exist")
        db.expunge(ticket)
        return ticket


def _persist_success(operation_id: str, result: dict[str, Any]) -> None:
    now = _now()
    with SessionLocal() as db:
        operation = (
            db.query(TicketOperation).filter(TicketOperation.operation_id == operation_id).first()
        )
        if not operation:
            return
        ticket = (
            db.query(Ticket)
            .filter(Ticket.internal_ticket_id == operation.internal_ticket_id)
            .first()
        )
        if not ticket:
            return

        operation.status = "succeeded"
        operation.provider_response = result
        operation.last_error = None
        operation.completed_at = now
        operation.updated_at = now

        external_ticket_id = result.get("ticket_id")
        if operation.action == "create" and external_ticket_id:
            ticket.provider_ticket_id = str(external_ticket_id)
            ticket.state = "open"
        elif operation.action == "close":
            ticket.state = "closed"
        elif operation.action == "update":
            ticket.state = "updating"
        elif operation.action == "comment":
            ticket.state = "open"
        ticket.latest_error = None
        ticket.updated_at = now
        BAKERY_OPERATIONS_TOTAL.labels(action=operation.action, status="succeeded").inc()
        db.commit()


def _persist_failure(operation_id: str, error: str) -> None:
    now = _now()
    with SessionLocal() as db:
        operation = (
            db.query(TicketOperation).filter(TicketOperation.operation_id == operation_id).first()
        )
        if not operation:
            return
        ticket = (
            db.query(Ticket)
            .filter(Ticket.internal_ticket_id == operation.internal_ticket_id)
            .first()
        )
        if not ticket:
            return

        operation.attempt_count += 1
        operation.last_error = error
        operation.updated_at = now

        if operation.attempt_count >= operation.max_attempts:
            operation.status = "dead_letter"
            operation.completed_at = now
            operation.next_attempt_at = None
            ticket.state = "error"
            BAKERY_DEAD_LETTER_TOTAL.labels(action=operation.action).inc()
            BAKERY_OPERATIONS_TOTAL.labels(action=operation.action, status="dead_letter").inc()
        else:
            operation.status = "failed"
            delay = _compute_backoff(operation.attempt_count)
            operation.next_attempt_at = now + timedelta(seconds=delay)
            ticket.state = "error"
            BAKERY_RETRIES_TOTAL.labels(action=operation.action).inc()
            BAKERY_OPERATIONS_TOTAL.labels(action=operation.action, status="failed").inc()

        ticket.latest_error = error
        ticket.updated_at = now
        db.commit()


def _process_operation(operation: TicketOperation) -> None:
    started = time.monotonic()
    ticket = _load_ticket(operation.internal_ticket_id)
    mixer = get_mixer(settings.active_provider)
    payload = _build_provider_payload(operation.action, ticket, operation.request_payload)
    result = asyncio.run(mixer.process_request(operation.action, payload))
    BAKERY_OPERATION_LATENCY_SECONDS.labels(action=operation.action).observe(
        max(time.monotonic() - started, 0.0)
    )
    if result.get("success"):
        _persist_success(operation.operation_id, result)
        return
    _persist_failure(operation.operation_id, str(result.get("error") or "provider request failed"))


def run_worker() -> None:
    logger.info(
        "Bakery worker started",
        provider=settings.active_provider,
        batch_size=settings.worker_batch_size,
        poll_interval_sec=settings.worker_poll_interval_sec,
    )
    while True:
        claimed = _claim_operations(settings.worker_batch_size)
        if not claimed:
            time.sleep(settings.worker_poll_interval_sec)
            continue

        for operation in claimed:
            try:
                _process_operation(operation)
            except Exception as exc:  # noqa: BLE001
                logger.exception(
                    "Operation execution failed",
                    operation_id=operation.operation_id,
                    error=str(exc),
                )
                _persist_failure(operation.operation_id, str(exc))


if __name__ == "__main__":
    run_worker()
