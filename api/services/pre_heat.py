#  ____                        _  ____      _
# |  _ \ ___  _   _ _ __   __| |/ ___|__ _| | _____
# | |_) / _ \| | | | '_ \ / _` | |   / _` | |/ / _ \
# |  __/ (_) | |_| | | | | (_| | |__| (_| |   <  __/
# |_|   \___/ \__,_|_| |_|\__,_|\____\__,_|_|\_\___|
#
"""Pre-heat service - Creates new alerts or increments existing ones."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime, timezone
from dateutil import parser as dateutil_parser
from api.models.models import Alert
from api.core.logging import get_logger

logger = get_logger(__name__)


async def pre_heat(payload: dict, db: AsyncSession, req_id: str) -> dict:
    """
    Intake Handler: Solely responsible for Alert table management.

    Args:
        payload: Alertmanager webhook payload
        db: Database session
        req_id: Request ID for tracing

    Returns:
        dict: Status and alert_id
    """
    alerts = payload.get("alerts", [])

    if not alerts:
        logger.warning("No alerts in payload", extra={"req_id": req_id})
        return {"status": "no_alerts"}

    # Process first alert (Alertmanager sends one alert per webhook in practice)
    alert_data = alerts[0]
    labels = alert_data.get("labels", {})
    alert_name = labels.get("alertname", "Unknown")
    alert_status = alert_data.get("status", "firing")

    # Use fingerprint or generate from labels
    fingerprint = (
        alert_data.get("fingerprint") or f"{alert_name}_{labels.get('instance', 'unknown')}"
    )

    logger.info(
        "Processing alert",
        extra={
            "req_id": req_id,
            "alert_name": alert_name,
            "alert_status": alert_status,
            "fingerprint": fingerprint,
        },
    )

    query = (
        select(Alert)
        .where(Alert.fingerprint == fingerprint, Alert.processing_status != "complete")
        .order_by(Alert.created_at.desc())
    )
    result = await db.execute(query)
    existing = result.scalars().first()

    if alert_status == "firing":
        if not existing:
            # Create fresh record; status 'new' triggers the Oven Service later
            # Parse startsAt or use current time as default
            starts_at = alert_data.get("startsAt")
            if starts_at and isinstance(starts_at, str):
                try:
                    starts_at = dateutil_parser.isoparse(starts_at)
                except (ValueError, TypeError):
                    starts_at = datetime.now(timezone.utc)
            elif not starts_at:
                starts_at = datetime.now(timezone.utc)

            new_alert = Alert(
                req_id=req_id,  # Use request ID from webhook
                fingerprint=fingerprint,
                alert_name=alert_name,
                group_name=alert_name,
                alert_status="firing",
                processing_status="new",
                severity=labels.get("severity", "unknown"),
                instance=labels.get("instance"),
                labels=labels,
                annotations=alert_data.get("annotations", {}),
                starts_at=starts_at,
                generator_url=alert_data.get("generatorURL"),
                counter=1,
            )
            db.add(new_alert)
            await db.commit()
            await db.refresh(new_alert)

            logger.info(
                "New alert created",
                extra={
                    "req_id": req_id,
                    "alert_id": new_alert.id,
                    "alert_name": alert_name,
                    "group_name": alert_name,
                },
            )
            return {"status": "created", "alert_id": new_alert.id}
        else:
            # Alert already exists, increment counter
            existing.counter += 1
            await db.commit()

            logger.info(
                "Alert counter incremented",
                extra={"req_id": req_id, "alert_id": existing.id, "counter": existing.counter},
            )
            return {"status": "counter_incremented", "alert_id": existing.id}

    elif alert_status == "resolved" and existing:
        existing.alert_status = "resolved"
        existing.ends_at = alert_data.get("endsAt")
        await db.commit()

        logger.info("Alert resolved", extra={"req_id": req_id, "alert_id": existing.id})
        return {"status": "resolved", "alert_id": existing.id}

    logger.debug(
        "Alert ignored",
        extra={"req_id": req_id, "alert_status": alert_status, "existing": existing is not None},
    )
    return {"status": "ignored"}
