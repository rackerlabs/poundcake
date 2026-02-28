#  ____                        _  ____      _
# |  _ \ ___  _   _ _ __   __| |/ ___|__ _| | _____
# | |_) / _ \| | | | '_ \ / _` | |   / _` | |/ / _ \
# |  __/ (_) | |_| | | | | (_| | |__| (_| |   <  __/
# |_|   \___/ \__,_|_| |_|\__,_|\____\__,_|_|\_\___|
#
"""Pre-heat service - Creates new orders or increments existing ones."""

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError
from datetime import datetime, timezone
from dateutil import parser as dateutil_parser
from api.models.models import Order
from api.core.config import get_settings
from api.core.logging import get_logger
from api.core.metrics import record_order_resolved_before_dish_start
from api.core.statuses import ORDER_TERMINAL_PROCESSING_STATUSES
from api.services.bakery_client import add_ticket_comment, close_ticket, poll_operation
from api.services.suppression_service import find_first_matching_suppression, save_suppressed_event

logger = get_logger(__name__)
settings = get_settings()
TERMINAL_TICKET_STATES = {"closed", "terminal"}


def _resolved_ticket_state() -> str:
    if settings.bakery_active_provider.lower() == "rackspace_core":
        return (
            settings.bakery_rackspace_confirmed_solved_status or "confirmed solved"
        ).lower().replace(" ", "_")
    return "closed"


async def _sync_ticket_on_alert_resolved(
    *,
    req_id: str,
    order: Order,
    alert_name: str,
    fingerprint: str,
) -> None:
    if not settings.bakery_enabled:
        return
    if not order.bakery_ticket_id or order.bakery_permanent_failure:
        return

    cleared_at = datetime.now(timezone.utc).isoformat()
    comment = (
        f"Alert cleared: {alert_name}\n"
        f"Fingerprint: {fingerprint}\n"
        f"Order ID: {order.id}\n"
        f"Cleared At: {cleared_at}"
    )
    try:
        await add_ticket_comment(req_id=req_id, ticket_id=order.bakery_ticket_id, comment=comment)
        close_payload = {
            "resolution_notes": (
                f"Alert cleared for order {order.id} "
                f"(fingerprint={fingerprint}); moving to confirmed solved."
            ),
            "state": _resolved_ticket_state(),
        }
        accepted = await close_ticket(
            req_id=req_id,
            ticket_id=order.bakery_ticket_id,
            payload=close_payload,
        )
        order.bakery_operation_id = accepted.get("operation_id")
        order.bakery_ticket_state = _resolved_ticket_state()
        operation_id = accepted.get("operation_id")
        if operation_id:
            op_payload = await poll_operation(operation_id)
            op_status = str(op_payload.get("status") or "")
            if op_status == "dead_letter":
                order.bakery_permanent_failure = True
                order.bakery_last_error = str(op_payload.get("last_error") or "dead_letter")
            elif op_status == "succeeded":
                order.bakery_permanent_failure = False
                order.bakery_last_error = None
    except TimeoutError:
        logger.info(
            "Bakery resolve operation still in progress",
            extra={
                "req_id": req_id,
                "order_id": order.id,
                "ticket_id": order.bakery_ticket_id,
                "operation_id": order.bakery_operation_id,
            },
        )
    except Exception as exc:  # noqa: BLE001
        order.bakery_last_error = str(exc)
        logger.error(
            "Failed to sync Bakery ticket on alert resolve",
            extra={"req_id": req_id, "order_id": order.id, "error": str(exc)},
        )


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
    alerts = payload.get("alerts", [])

    if not alerts:
        logger.warning("No alerts in payload", extra={"req_id": req_id})
        return {"status": "no_alerts", "results": []}

    results: list[dict] = []

    for alert_data in alerts:
        labels = alert_data.get("labels", {})
        alert_name = labels.get("alertname", "Unknown")
        group_name = labels.get("group_name") or alert_name
        alert_status = alert_data.get("status", "firing")

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

        if db.in_transaction():
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

                if alert_status == "firing":
                    if not existing:
                        reusable_ticket_id: str | None = None
                        reusable_ticket_state: str | None = None
                        if settings.bakery_enabled:
                            previous_result = await db.execute(
                                select(Order)
                                .where(
                                    Order.fingerprint == fingerprint,
                                    Order.is_active.is_(False),
                                    Order.bakery_ticket_id.is_not(None),
                                    Order.bakery_permanent_failure.is_(False),
                                )
                                .order_by(Order.updated_at.desc())
                                .with_for_update()
                            )
                            previous_order = previous_result.scalars().first()
                            if (
                                previous_order
                                and previous_order.bakery_ticket_id
                                and (previous_order.bakery_ticket_state or "").lower()
                                not in TERMINAL_TICKET_STATES
                            ):
                                reusable_ticket_id = previous_order.bakery_ticket_id
                                reusable_ticket_state = previous_order.bakery_ticket_state or "open"

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
                            bakery_ticket_id=reusable_ticket_id,
                            bakery_ticket_state=reusable_ticket_state,
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
                            updated_at=datetime.now(timezone.utc),
                        )
                    )

                    logger.info(
                        "Order counter incremented",
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
                    continue

                if alert_status == "resolved" and existing:
                    resolved_before_dish = existing.processing_status == "new"
                    existing.alert_status = "resolved"
                    ends_at = alert_data.get("endsAt")
                    if ends_at and isinstance(ends_at, str):
                        try:
                            ends_at = dateutil_parser.isoparse(ends_at)
                        except (ValueError, TypeError):
                            ends_at = datetime.now(timezone.utc)
                    existing.ends_at = ends_at
                    if existing.processing_status not in ORDER_TERMINAL_PROCESSING_STATUSES:
                        existing.processing_status = "canceled"
                    existing.is_active = False
                    existing.updated_at = datetime.now(timezone.utc)
                    await _sync_ticket_on_alert_resolved(
                        req_id=req_id,
                        order=existing,
                        alert_name=alert_name,
                        fingerprint=fingerprint,
                    )

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
