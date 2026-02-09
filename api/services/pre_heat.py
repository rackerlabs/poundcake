#  ____                        _  ____      _
# |  _ \ ___  _   _ _ __   __| |/ ___|__ _| | _____
# | |_) / _ \| | | | '_ \ / _` | |   / _` | |/ / _ \
# |  __/ (_) | |_| | | | | (_| | |__| (_| |   <  __/
# |_|   \___/ \__,_|_| |_|\__,_|\____\__,_|_|\_\___|
#
"""Pre-heat service - Creates new orders or increments existing ones."""

from sqlalchemy.orm import Session
from datetime import datetime, timezone
from dateutil import parser as dateutil_parser
from api.models.models import Order
from api.core.logging import get_logger

logger = get_logger(__name__)


def pre_heat(payload: dict, db: Session, req_id: str) -> dict:
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
        return {"status": "no_alerts"}

    # Process first alert (Alertmanager sends one alert per webhook in practice)
    alert_data = alerts[0]
    labels = alert_data.get("labels", {})
    alert_name = labels.get("alertname", "Unknown")
    group_name = labels.get("group_name") or alert_name
    alert_status = alert_data.get("status", "firing")

    # Use fingerprint or generate from labels
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

    existing = (
        db.query(Order)
        .filter(
            Order.fingerprint == fingerprint,
            Order.processing_status.notin_(["complete", "canceled"]),
        )
        .order_by(Order.created_at.desc())
        .first()
    )

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
                severity=labels.get("severity", "unknown"),
                instance=labels.get("instance"),
                labels=labels,
                annotations=alert_data.get("annotations", {}),
                raw_data=alert_data,
                counter=1,
                starts_at=starts_at,
            )
            db.add(new_order)
            db.commit()
            db.refresh(new_order)

            logger.info(
                "New order created",
                extra={
                    "req_id": req_id,
                    "order_id": new_order.id,
                    "alert_name": alert_name,
                    "group_name": group_name,
                },
            )
            return {"status": "created", "order_id": new_order.id}
        else:
            # Order already exists; increment counter
            existing.counter += 1
            existing.updated_at = datetime.now(timezone.utc)
            db.commit()

            logger.info(
                "Order counter incremented",
                extra={"req_id": req_id, "order_id": existing.id, "counter": existing.counter},
            )
            return {"status": "counter_incremented", "order_id": existing.id}

    elif alert_status == "resolved" and existing:
        existing.alert_status = "resolved"
        ends_at = alert_data.get("endsAt")
        if ends_at and isinstance(ends_at, str):
            try:
                ends_at = dateutil_parser.isoparse(ends_at)
            except (ValueError, TypeError):
                ends_at = datetime.now(timezone.utc)
        existing.ends_at = ends_at
        existing.processing_status = "canceled"
        existing.updated_at = datetime.now(timezone.utc)
        db.commit()

        logger.info("Order resolved", extra={"req_id": req_id, "order_id": existing.id})
        return {"status": "resolved", "order_id": existing.id}

    logger.debug(
        "Order ignored",
        extra={"req_id": req_id, "alert_status": alert_status, "existing": existing is not None},
    )
    return {"status": "ignored"}
