#  ____                        _  ____      _
# |  _ \ ___  _   _ _ __   __| |/ ___|__ _| | _____
# | |_) / _ \| | | | '_ \ / _` | |   / _` | |/ / _ \
# |  __/ (_) | |_| | | | | (_| | |__| (_| |   <  __/
# |_|   \___/ \__,_|_| |_|\__,_|\____\__,_|_|\_\___|
#
"""Pre-heat service - Creates new orders or increments existing ones."""

import inspect
from collections import Counter
from sqlalchemy import select, update, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError
from datetime import datetime, timezone
from dateutil import parser as dateutil_parser
from api.models.models import Order
from api.core.config import get_settings
from api.core.logging import get_logger
from api.core.metrics import record_order_resolved_before_dish_start
from api.core.statuses import can_transition_to_resolving, is_order_terminal, should_keep_active
from api.services.suppression_service import find_first_matching_suppression, save_suppressed_event

logger = get_logger(__name__)
settings = get_settings()


async def _in_transaction(db: AsyncSession) -> bool:
    """Return transaction state for real sessions and async-mocked sessions."""
    in_tx = db.in_transaction()
    if inspect.isawaitable(in_tx):
        in_tx = await in_tx
    return bool(in_tx)


def _label_text(labels: dict, key: str) -> str:
    return str(labels.get(key) or "").strip()


def _is_root_cause(labels: dict) -> bool:
    return _label_text(labels, "root_cause").lower() == "true"


def _alert_processing_priority(alert_data: dict) -> tuple[int, int]:
    labels = alert_data.get("labels", {}) if isinstance(alert_data.get("labels"), dict) else {}
    status = str(alert_data.get("status") or "firing").strip().lower()
    return (0 if status == "firing" else 1, 0 if _is_root_cause(labels) else 1)


def _affected_workload(labels: dict) -> str | None:
    namespace = _label_text(labels, "namespace")
    for key in ("daemonset", "deployment", "statefulset", "pod", "poddisruptionbudget", "service"):
        value = _label_text(labels, key)
        if value:
            return f"{namespace}/{value}" if namespace else value
    return None


def _child_summary(alert_data: dict, *, fingerprint: str, alert_name: str) -> dict:
    labels = alert_data.get("labels", {}) if isinstance(alert_data.get("labels"), dict) else {}
    annotations = (
        alert_data.get("annotations", {}) if isinstance(alert_data.get("annotations"), dict) else {}
    )
    now = datetime.now(timezone.utc).isoformat()
    return {
        "fingerprint": fingerprint,
        "alert_name": alert_name,
        "group_name": _label_text(labels, "group_name") or alert_name,
        "severity": _label_text(labels, "severity") or "unknown",
        "status": str(alert_data.get("status") or "firing").strip().lower(),
        "correlation_key": _label_text(labels, "correlation_key"),
        "correlation_scope": _label_text(labels, "correlation_scope"),
        "affected_node": _label_text(labels, "affected_node") or _label_text(labels, "node"),
        "namespace": _label_text(labels, "namespace"),
        "workload": _affected_workload(labels),
        "summary": str(annotations.get("summary") or "").strip(),
        "starts_at": alert_data.get("startsAt"),
        "ends_at": alert_data.get("endsAt"),
        "last_seen_at": now,
        "counter": 1,
    }


def _rebuild_correlation_summary(correlation: dict) -> None:
    children = [child for child in correlation.get("children", []) if isinstance(child, dict)]
    active_children = [child for child in children if child.get("status") != "resolved"]
    correlation["child_count"] = len(children)
    correlation["active_child_count"] = len(active_children)
    correlation["child_counts_by_group"] = dict(
        sorted(Counter(str(child.get("group_name") or "unknown") for child in children).items())
    )
    correlation["affected_namespaces"] = sorted(
        {
            str(child.get("namespace"))
            for child in children
            if str(child.get("namespace") or "").strip()
        }
    )
    correlation["affected_workloads"] = sorted(
        {
            str(child.get("workload"))
            for child in children
            if str(child.get("workload") or "").strip()
        }
    )
    correlation["affected_nodes"] = sorted(
        {
            str(child.get("affected_node"))
            for child in children
            if str(child.get("affected_node") or "").strip()
        }
    )


def _attach_child_alert(
    parent: Order, alert_data: dict, *, fingerprint: str, alert_name: str
) -> None:
    raw_data = dict(parent.raw_data or {})
    correlation = (
        raw_data.get("correlation") if isinstance(raw_data.get("correlation"), dict) else {}
    )
    labels = alert_data.get("labels", {}) if isinstance(alert_data.get("labels"), dict) else {}
    correlation.setdefault("key", _label_text(labels, "correlation_key"))
    correlation.setdefault("scope", _label_text(labels, "correlation_scope"))
    correlation.setdefault("root_order_id", parent.id)
    children = [child for child in correlation.get("children", []) if isinstance(child, dict)]
    entry = _child_summary(alert_data, fingerprint=fingerprint, alert_name=alert_name)

    for idx, child in enumerate(children):
        if child.get("fingerprint") == fingerprint:
            entry["counter"] = int(child.get("counter") or 0) + 1
            children[idx] = {**child, **entry}
            break
    else:
        children.append(entry)

    correlation["children"] = children
    correlation["last_child_seen_at"] = entry["last_seen_at"]
    _rebuild_correlation_summary(correlation)
    raw_data["correlation"] = correlation
    parent.raw_data = raw_data
    parent.counter = int(parent.counter or 0) + 1
    parent.updated_at = datetime.now(timezone.utc)


async def _find_active_root_parent(
    db: AsyncSession, *, correlation_key: str, fingerprint: str
) -> Order | None:
    if not correlation_key:
        return None
    result = await db.execute(
        select(Order)
        .where(Order.is_active.is_(True))
        .order_by(Order.created_at.desc())
        .limit(200)
        .with_for_update()
    )
    for order in result.scalars().all():
        labels = order.labels or {}
        if (
            order.fingerprint != fingerprint
            and _label_text(labels, "correlation_key") == correlation_key
            and _is_root_cause(labels)
        ):
            return order
    return None


async def pre_heat(payload: dict, db: AsyncSession, req_id: str) -> dict:
    """
    Intake Handler: Solely responsible for Order table management.

    Args:
        payload: Alertmanager webhook payload
        db: Database session
        req_id: Request ID for tracing

    Returns:
        dict: Status and order_id
    """
    alerts = sorted(payload.get("alerts", []), key=_alert_processing_priority)

    if not alerts:
        logger.warning("No alerts in payload", extra={"req_id": req_id})
        return {"status": "no_alerts", "results": []}

    results: list[dict] = []

    for alert_data in alerts:
        labels = alert_data.get("labels", {})
        alert_name = labels.get("alertname", "Unknown")
        group_name = labels.get("group_name") or alert_name
        alert_status = alert_data.get("status", "firing")
        correlation_key = _label_text(labels, "correlation_key")
        is_root_cause = _is_root_cause(labels)

        # Prefer Alertmanager fingerprint; fallback to derived value
        fingerprint = (
            alert_data.get("fingerprint") or f"{alert_name}_{labels.get('instance', 'unknown')}"
        )

        logger.info(
            "Processing order",
            extra={
                "req_id": req_id,
                "alert_name": alert_name,
                "alert_status": alert_status,
                "fingerprint": fingerprint,
            },
        )

        if settings.suppressions_enabled:
            suppression = await find_first_matching_suppression(
                db=db,
                labels=labels,
                received_at=datetime.now(timezone.utc),
            )
            if suppression:
                await save_suppressed_event(
                    db=db,
                    suppression=suppression,
                    alert_data=alert_data,
                    req_id=req_id,
                    received_at=datetime.now(timezone.utc),
                )
                await db.commit()
                logger.info(
                    "Alert suppressed by active suppression window",
                    extra={
                        "req_id": req_id,
                        "suppression_id": suppression.id,
                        "fingerprint": fingerprint,
                        "alert_name": alert_name,
                    },
                )
                results.append(
                    {
                        "status": "ignored_suppressed",
                        "suppression_id": suppression.id,
                        "order_id": None,
                        "fingerprint": fingerprint,
                        "alert_name": alert_name,
                        "alert_status": alert_status,
                    }
                )
                continue

        if await _in_transaction(db):
            await db.rollback()

        try:
            async with db.begin():
                result = await db.execute(
                    select(Order)
                    .where(
                        Order.fingerprint == fingerprint,
                        Order.is_active.is_(True),
                    )
                    .order_by(Order.created_at.desc())
                    .with_for_update()
                )
                existing = result.scalars().first()

                # Resolved notifications can arrive after the order was already
                # made inactive by dish completion. Fall back to the latest
                # unresolved order for this fingerprint so alert_status can be
                # updated correctly.
                if alert_status == "resolved" and not existing:
                    fallback_result = await db.execute(
                        select(Order)
                        .where(
                            Order.fingerprint == fingerprint,
                            func.lower(Order.alert_status) != "resolved",
                        )
                        .order_by(Order.created_at.desc())
                        .with_for_update()
                    )
                    existing = fallback_result.scalars().first()

                if not existing and correlation_key and not is_root_cause:
                    parent = await _find_active_root_parent(
                        db, correlation_key=correlation_key, fingerprint=fingerprint
                    )
                    if parent:
                        _attach_child_alert(
                            parent,
                            alert_data,
                            fingerprint=fingerprint,
                            alert_name=alert_name,
                        )
                        logger.info(
                            "Alert correlated to active root order",
                            extra={
                                "req_id": req_id,
                                "parent_order_id": parent.id,
                                "fingerprint": fingerprint,
                                "alert_name": alert_name,
                                "correlation_key": correlation_key,
                            },
                        )
                        results.append(
                            {
                                "status": "correlated_child",
                                "order_id": parent.id,
                                "parent_order_id": parent.id,
                                "fingerprint": fingerprint,
                                "alert_name": alert_name,
                                "alert_status": alert_status,
                                "correlation_key": correlation_key,
                            }
                        )
                        continue

                if alert_status == "firing":
                    if not existing:
                        # Create fresh record; status 'new' triggers the Dish flow later
                        # Parse startsAt or use current time as default
                        starts_at = alert_data.get("startsAt")
                        if starts_at and isinstance(starts_at, str):
                            try:
                                starts_at = dateutil_parser.isoparse(starts_at)
                            except (ValueError, TypeError):
                                starts_at = datetime.now(timezone.utc)
                        elif not starts_at:
                            starts_at = datetime.now(timezone.utc)

                        new_order = Order(
                            req_id=req_id,  # Use request ID from webhook
                            fingerprint=fingerprint,
                            alert_group_name=group_name,
                            alert_status="firing",
                            processing_status="new",
                            is_active=True,
                            severity=labels.get("severity", "unknown"),
                            instance=labels.get("instance"),
                            labels=labels,
                            annotations=alert_data.get("annotations", {}),
                            raw_data=alert_data,
                            counter=1,
                            starts_at=starts_at,
                            remediation_outcome="pending",
                            clear_timeout_sec=None,
                            clear_deadline_at=None,
                            clear_timed_out_at=None,
                            auto_close_eligible=False,
                        )
                        db.add(new_order)
                        await db.flush()

                        logger.info(
                            "New order created",
                            extra={
                                "req_id": req_id,
                                "order_id": new_order.id,
                                "alert_name": alert_name,
                                "group_name": group_name,
                            },
                        )
                        results.append(
                            {
                                "status": "created",
                                "order_id": new_order.id,
                                "fingerprint": fingerprint,
                                "alert_name": alert_name,
                                "alert_status": alert_status,
                            }
                        )
                        continue

                    # Order already exists; increment counter atomically
                    await db.execute(
                        update(Order)
                        .where(Order.id == existing.id)
                        .values(
                            counter=Order.counter + 1,
                            alert_status="firing",
                            processing_status=(
                                "new"
                                if (existing.processing_status or "").lower()
                                in {"resolving", "waiting_ticket_close"}
                                else Order.processing_status
                            ),
                            ends_at=None,
                            is_active=True,
                            updated_at=datetime.now(timezone.utc),
                        )
                    )
                    reopened_from_resolving = (existing.processing_status or "").lower() in {
                        "resolving",
                        "waiting_ticket_close",
                    }

                    logger.info(
                        "Order counter incremented",
                        extra={
                            "req_id": req_id,
                            "order_id": existing.id,
                            "reopened_from_resolving": reopened_from_resolving,
                        },
                    )
                    results.append(
                        {
                            "status": "counter_incremented",
                            "order_id": existing.id,
                            "fingerprint": fingerprint,
                            "alert_name": alert_name,
                            "alert_status": alert_status,
                        }
                    )
                    continue

                if alert_status == "resolved" and existing:
                    resolved_before_dish = existing.processing_status == "new"

                    ends_at = alert_data.get("endsAt")
                    if ends_at and isinstance(ends_at, str):
                        try:
                            ends_at = dateutil_parser.isoparse(ends_at)
                        except (ValueError, TypeError):
                            ends_at = datetime.now(timezone.utc)

                    existing.alert_status = "resolved"
                    existing.ends_at = ends_at
                    if can_transition_to_resolving(existing.processing_status, "alert_resolved"):
                        existing.processing_status = "resolving"
                    if is_order_terminal(existing.processing_status):
                        existing.is_active = False
                    else:
                        existing.is_active = should_keep_active(existing.processing_status)
                    existing.updated_at = datetime.now(timezone.utc)

                    if resolved_before_dish:
                        logger.warning(
                            "Order resolved before any dish started",
                            extra={
                                "req_id": req_id,
                                "order_id": existing.id,
                                "alert_name": alert_name,
                                "group_name": group_name,
                                "severity": existing.severity,
                            },
                        )
                        record_order_resolved_before_dish_start(
                            group_name, existing.severity or "unknown"
                        )

                    logger.info("Order resolved", extra={"req_id": req_id, "order_id": existing.id})
                    results.append(
                        {
                            "status": "resolved",
                            "order_id": existing.id,
                            "fingerprint": fingerprint,
                            "alert_name": alert_name,
                            "alert_status": alert_status,
                        }
                    )
                    continue

                logger.debug(
                    "Order ignored",
                    extra={
                        "req_id": req_id,
                        "alert_status": alert_status,
                        "existing": existing is not None,
                    },
                )
                results.append(
                    {
                        "status": "ignored",
                        "order_id": existing.id if existing else None,
                        "fingerprint": fingerprint,
                        "alert_name": alert_name,
                        "alert_status": alert_status,
                    }
                )
        except IntegrityError:
            await db.rollback()
            async with db.begin():
                result = await db.execute(
                    select(Order)
                    .where(
                        Order.fingerprint == fingerprint,
                        Order.is_active.is_(True),
                    )
                    .order_by(Order.created_at.desc())
                    .with_for_update()
                )
                existing = result.scalars().first()
                if existing:
                    await db.execute(
                        update(Order)
                        .where(Order.id == existing.id)
                        .values(
                            counter=Order.counter + 1,
                            updated_at=datetime.now(timezone.utc),
                        )
                    )
                    logger.info(
                        "Order counter incremented after conflict",
                        extra={"req_id": req_id, "order_id": existing.id},
                    )
                    results.append(
                        {
                            "status": "counter_incremented",
                            "order_id": existing.id,
                            "fingerprint": fingerprint,
                            "alert_name": alert_name,
                            "alert_status": alert_status,
                        }
                    )
                else:
                    logger.error(
                        "Order conflict without active order",
                        extra={"req_id": req_id, "fingerprint": fingerprint},
                    )
                    results.append(
                        {
                            "status": "conflict",
                            "order_id": None,
                            "fingerprint": fingerprint,
                            "alert_name": alert_name,
                            "alert_status": alert_status,
                        }
                    )

    if len(results) == 1:
        return {
            "status": results[0]["status"],
            "order_id": results[0].get("order_id"),
            "results": results,
        }

    return {"status": "batch", "order_id": None, "results": results}
