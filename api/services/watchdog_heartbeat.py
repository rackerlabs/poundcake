"""Watchdog/deadman heartbeat handling."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.config import get_settings
from api.core.database import SessionLocal
from api.core.logging import get_logger
from api.core.statuses import can_transition_to_resolving, is_order_terminal, should_keep_active
from api.models.models import Order, WatchdogHeartbeatState

logger = get_logger(__name__)

WATCHDOG_HEARTBEAT_KEY = "watchdog"
WATCHDOG_MISSING_ALERT_NAME = "PoundCakeWatchdogMissing"
WATCHDOG_MISSING_GROUP_NAME = "poundcake-watchdog-missing"
WATCHDOG_MISSING_FINGERPRINT = f"poundcake:{WATCHDOG_HEARTBEAT_KEY}:missing"

_CHECKER_TASK: asyncio.Task | None = None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _label_text(labels: dict[str, Any], key: str) -> str:
    return str(labels.get(key) or "").strip()


def is_watchdog_alert(labels: dict[str, Any]) -> bool:
    """Return true when labels represent the always-firing Watchdog heartbeat."""
    alert_name = _label_text(labels, "alertname").lower()
    group_name = _label_text(labels, "group_name").lower()
    if group_name == "watchdog":
        return True
    return alert_name == "watchdog" or alert_name.startswith(("watchdog-", "watchdog_"))


def _payload_snapshot(alert_data: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": alert_data.get("status"),
        "labels": alert_data.get("labels") if isinstance(alert_data.get("labels"), dict) else {},
        "annotations": (
            alert_data.get("annotations") if isinstance(alert_data.get("annotations"), dict) else {}
        ),
        "startsAt": alert_data.get("startsAt"),
        "endsAt": alert_data.get("endsAt"),
        "fingerprint": alert_data.get("fingerprint"),
    }


async def _find_active_missing_order(db: AsyncSession) -> Order | None:
    result = await db.execute(
        select(Order)
        .where(
            Order.fingerprint == WATCHDOG_MISSING_FINGERPRINT,
            Order.is_active.is_(True),
        )
        .order_by(Order.created_at.desc())
        .with_for_update()
    )
    return result.scalars().first()


def _mark_order_resolved(order: Order, *, now: datetime) -> None:
    order.alert_status = "resolved"
    order.ends_at = now
    if can_transition_to_resolving(order.processing_status, "alert_resolved"):
        order.processing_status = "resolving"
    if is_order_terminal(order.processing_status):
        order.is_active = False
    else:
        order.is_active = should_keep_active(order.processing_status)
    order.updated_at = now


async def _resolve_missing_order(
    db: AsyncSession,
    state: WatchdogHeartbeatState,
    *,
    now: datetime,
) -> int | None:
    order = await _find_active_missing_order(db)
    if not order or str(order.alert_status or "").lower() == "resolved":
        return None

    _mark_order_resolved(order, now=now)
    state.synthetic_order_id = order.id
    state.updated_at = now
    logger.info(
        "Watchdog heartbeat resumed; synthetic incident resolved", extra={"order_id": order.id}
    )
    return order.id


async def _find_active_legacy_watchdog_orders(db: AsyncSession) -> list[Order]:
    result = await db.execute(
        select(Order)
        .where(
            Order.is_active.is_(True),
            or_(
                Order.fingerprint.is_(None),
                Order.fingerprint != WATCHDOG_MISSING_FINGERPRINT,
            ),
            or_(
                Order.alert_group_name == WATCHDOG_HEARTBEAT_KEY,
                Order.alert_group_name == "Watchdog",
                Order.alert_group_name.like("watchdog-%"),
                Order.alert_group_name.like("watchdog_%"),
            ),
        )
        .order_by(Order.created_at.asc())
        .with_for_update()
    )
    return list(result.scalars().all())


async def _resolve_legacy_watchdog_orders(db: AsyncSession, *, now: datetime) -> list[int]:
    resolved_order_ids: list[int] = []
    for order in await _find_active_legacy_watchdog_orders(db):
        if str(order.alert_status or "").lower() == "resolved":
            continue
        _mark_order_resolved(order, now=now)
        resolved_order_ids.append(order.id)

    if resolved_order_ids:
        logger.info(
            "Watchdog heartbeat resumed; legacy incidents resolved",
            extra={"order_ids": resolved_order_ids},
        )
    return resolved_order_ids


async def record_watchdog_heartbeat(
    db: AsyncSession,
    alert_data: dict[str, Any],
    *,
    fingerprint: str,
    alert_name: str,
    req_id: str,
) -> dict[str, Any]:
    """Record a Watchdog webhook without creating a normal incident order."""
    settings = get_settings()
    if not settings.watchdog_heartbeat_enabled:
        return {
            "status": "watchdog_heartbeat_disabled",
            "order_id": None,
            "fingerprint": fingerprint,
            "alert_name": alert_name,
            "alert_status": alert_data.get("status", "firing"),
        }

    now = _now()
    alert_status = str(alert_data.get("status") or "firing").strip().lower()

    async with db.begin():
        result = await db.execute(
            select(WatchdogHeartbeatState)
            .where(WatchdogHeartbeatState.heartbeat_key == WATCHDOG_HEARTBEAT_KEY)
            .with_for_update()
        )
        state = result.scalars().first()
        if not state:
            state = WatchdogHeartbeatState(
                heartbeat_key=WATCHDOG_HEARTBEAT_KEY,
                created_at=now,
                updated_at=now,
            )
            db.add(state)

        state.alert_name = alert_name
        state.alert_fingerprint = fingerprint
        state.last_status = alert_status
        state.last_received_at = now
        state.last_payload = _payload_snapshot(alert_data)
        state.updated_at = now

        resolved_order_id = None
        resolved_legacy_order_ids: list[int] = []
        if alert_status == "firing":
            state.last_seen_at = now
            state.missing_since = None
            resolved_order_id = await _resolve_missing_order(db, state, now=now)
            resolved_legacy_order_ids = await _resolve_legacy_watchdog_orders(db, now=now)

    logger.info(
        "Watchdog heartbeat recorded",
        extra={
            "req_id": req_id,
            "alert_status": alert_status,
            "fingerprint": fingerprint,
            "resolved_order_id": resolved_order_id,
            "resolved_legacy_order_ids": resolved_legacy_order_ids,
        },
    )
    return {
        "status": "watchdog_heartbeat_recorded",
        "order_id": resolved_order_id,
        "legacy_order_ids": resolved_legacy_order_ids,
        "fingerprint": fingerprint,
        "alert_name": alert_name,
        "alert_status": alert_status,
        "heartbeat_key": WATCHDOG_HEARTBEAT_KEY,
    }


async def check_watchdog_heartbeat_once(db: AsyncSession) -> dict[str, Any]:
    """Open or resolve the synthetic Watchdog-missing incident."""
    settings = get_settings()
    if not settings.watchdog_heartbeat_enabled:
        return {"status": "disabled", "order_id": None}

    now = _now()
    threshold = max(int(settings.watchdog_heartbeat_missing_threshold_seconds or 300), 1)
    cutoff = now - timedelta(seconds=threshold)

    try:
        async with db.begin():
            result = await db.execute(
                select(WatchdogHeartbeatState)
                .where(WatchdogHeartbeatState.heartbeat_key == WATCHDOG_HEARTBEAT_KEY)
                .with_for_update()
            )
            state = result.scalars().first()
            if not state:
                state = WatchdogHeartbeatState(
                    heartbeat_key=WATCHDOG_HEARTBEAT_KEY,
                    last_status="never_seen",
                    last_received_at=None,
                    last_seen_at=None,
                    missing_since=now,
                    created_at=now,
                    updated_at=now,
                )
                db.add(state)
                return {"status": "pending_initial_heartbeat", "order_id": None}

            last_seen = _aware(state.last_seen_at)
            if last_seen and last_seen >= cutoff:
                resolved_order_id = await _resolve_missing_order(db, state, now=now)
                return {
                    "status": "healthy" if resolved_order_id is None else "resolved",
                    "order_id": resolved_order_id,
                }

            missing_since = _aware(state.missing_since)
            if not last_seen and missing_since and missing_since >= cutoff:
                state.updated_at = now
                return {"status": "pending_initial_heartbeat", "order_id": None}

            state.missing_since = state.missing_since or now
            state.updated_at = now

            existing = await _find_active_missing_order(db)
            if existing:
                if str(existing.alert_status or "").lower() == "resolved":
                    existing.alert_status = "firing"
                    existing.processing_status = "new"
                    existing.ends_at = None
                    existing.counter = int(existing.counter or 0) + 1
                    existing.updated_at = now
                    state.synthetic_order_id = existing.id
                    return {"status": "reopened", "order_id": existing.id}
                state.synthetic_order_id = existing.id
                return {"status": "already_firing", "order_id": existing.id}

            order = Order(
                req_id="SYSTEM-WATCHDOG",
                fingerprint=WATCHDOG_MISSING_FINGERPRINT,
                alert_group_name=WATCHDOG_MISSING_GROUP_NAME,
                alert_status="firing",
                processing_status="new",
                is_active=True,
                remediation_outcome="pending",
                clear_timeout_sec=None,
                clear_deadline_at=None,
                clear_timed_out_at=None,
                auto_close_eligible=False,
                severity="critical",
                instance=None,
                labels={
                    "alertname": WATCHDOG_MISSING_ALERT_NAME,
                    "group_name": WATCHDOG_MISSING_GROUP_NAME,
                    "severity": "critical",
                    "root_cause": "true",
                    "correlation_scope": "watchdog",
                    "correlation_key": f"watchdog/{WATCHDOG_HEARTBEAT_KEY}",
                },
                annotations={
                    "summary": "PoundCake Watchdog heartbeat is missing",
                    "description": (
                        "The always-firing Watchdog alert has not been received by "
                        f"PoundCake for at least {threshold} seconds."
                    ),
                },
                raw_data={
                    "source": "poundcake-watchdog-heartbeat",
                    "heartbeat_key": WATCHDOG_HEARTBEAT_KEY,
                    "last_seen_at": last_seen.isoformat() if last_seen else None,
                    "threshold_seconds": threshold,
                },
                counter=1,
                starts_at=state.missing_since or now,
                ends_at=None,
                created_at=now,
                updated_at=now,
            )
            db.add(order)
            await db.flush()
            state.synthetic_order_id = order.id
            state.updated_at = now
            logger.warning(
                "Watchdog heartbeat missing; synthetic incident opened",
                extra={"order_id": order.id},
            )
            return {"status": "created", "order_id": order.id}
    except IntegrityError:
        await db.rollback()
        return {"status": "conflict", "order_id": None}


async def _checker_loop() -> None:
    settings = get_settings()
    interval = max(int(settings.watchdog_heartbeat_check_interval_seconds or 30), 5)
    while True:
        await asyncio.sleep(interval)
        try:
            async with SessionLocal() as db:
                await check_watchdog_heartbeat_once(db)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("Watchdog heartbeat check failed", extra={"error": str(exc)})


async def start_watchdog_heartbeat_checker() -> None:
    """Start the background Watchdog heartbeat checker."""
    global _CHECKER_TASK
    settings = get_settings()
    if not settings.watchdog_heartbeat_enabled:
        logger.info("Watchdog heartbeat checker disabled")
        return
    if _CHECKER_TASK and not _CHECKER_TASK.done():
        return
    _CHECKER_TASK = asyncio.create_task(_checker_loop(), name="watchdog-heartbeat-checker")


async def stop_watchdog_heartbeat_checker() -> None:
    """Stop the background Watchdog heartbeat checker."""
    global _CHECKER_TASK
    if not _CHECKER_TASK:
        return
    _CHECKER_TASK.cancel()
    try:
        await _CHECKER_TASK
    except asyncio.CancelledError:
        pass
    _CHECKER_TASK = None
