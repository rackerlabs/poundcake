# ____                        _  ____      _
# |  _ \ ___  _   _ _ __   __| |/ ___|__ _| | _____
# | |_) / _ \| | | | '_ \ / _` | |   / _` | |/ / _ \
# |  __/ (_) | |_| | | | | (_| | |__| (_| |   <  __/
# |_|   \___/ \__,_|_| |_|\__,_|\____\__,_|_|\_\___|
#
# ╔════════════════════════════════════════════════════════════════╗
# ____                        _  ____      _         
# |  _ \ ___  _   _ _ __   __| |/ ___|__ _| | _____ 
# | |_) / _ \| | | | '_ \ / _` | |   / _` | |/ / _ \
# |  __/ (_) | |_| | | | | (_| | |__| (_| |   <  __/
# |_|   \___/ \__,_|_| |_|\__,_|\____\__,_|_|\_\___|
# ╚════════════════════════════════════════════════════════════════╝
#
"""Pre-heat service for alert ingestion and management."""

from datetime import datetime
from typing import List
from sqlalchemy.orm import Session

from api.core.logging import get_logger
from api.models.models import Alert
from api.schemas.schemas import AlertmanagerWebhook

logger = get_logger(__name__)


def pre_heat(webhook_data: AlertmanagerWebhook, req_id: str, db: Session) -> List[Alert]:
    """Pre-heat function: Insert or update alerts table based on alert state.

    Logic:
    1. If fingerprint exists with processing_status="complete" AND webhook status="firing"
       → Insert as NEW alert (new occurrence)

    2. If fingerprint exists with processing_status!="complete" AND webhook status="firing"
       → Update counter (alert is still being processed or is new)

    3. If fingerprint exists with processing_status!="complete" AND webhook status="resolved"
       → Update alert_status to "resolved"

    Args:
        webhook_data: The Alertmanager webhook payload
        req_id: Request ID from middleware
        db: Database session

    Returns:
        List of Alert objects that were created or updated
    """
    processed_alerts = []
    
    # Extract group_name from groupLabels (used for recipe matching)
    group_name = webhook_data.groupLabels.get("alertname")

    for alert_data in webhook_data.alerts:
        try:
            # Query for existing alert with this fingerprint
            existing_alert = (
                db.query(Alert).filter(Alert.fingerprint == alert_data.fingerprint).first()
            )

            webhook_status = alert_data.status  # "firing" or "resolved"

            # Extract fields from labels (with safe defaults for optional fields)
            alert_name = alert_data.labels.alertname
            severity = getattr(alert_data.labels, "severity", None)
            instance = getattr(alert_data.labels, "instance", None)
            prometheus = getattr(alert_data.labels, "prometheus", None)

            # Case 1: No existing alert → Insert as new
            if not existing_alert:
                logger.info(
                    "Pre-heat: No existing alert, creating new",
                    extra={"req_id": req_id, "fingerprint": alert_data.fingerprint},
                )

                alert = Alert(
                    req_id=req_id,
                    fingerprint=alert_data.fingerprint,
                    alert_status=webhook_status,
                    processing_status="new",
                    alert_name=alert_name,
                    group_name=group_name,
                    severity=severity,
                    instance=instance,
                    prometheus=prometheus,
                    labels=alert_data.labels.model_dump(mode="json"),
                    annotations=(
                        alert_data.annotations.model_dump(mode="json")
                        if alert_data.annotations
                        else None
                    ),
                    starts_at=alert_data.startsAt,
                    ends_at=alert_data.endsAt,
                    generator_url=alert_data.generatorURL,
                    raw_data=alert_data.model_dump(mode="json"),
                    counter=1,
                )
                db.add(alert)
                db.flush()  # Get the ID without committing
                processed_alerts.append(alert)

                logger.info(
                    f"Pre-heat: Created new alert id={alert.id}",
                    extra={"req_id": req_id, "fingerprint": alert_data.fingerprint},
                )

            # Case 2: Alert exists with processing_status="complete" AND webhook says "firing"
            # → Insert as NEW alert (new occurrence of a completed alert)
            elif existing_alert.processing_status == "complete" and webhook_status == "firing":
                logger.info(
                    "Pre-heat: Completed alert fired again, creating new occurrence",
                    extra={
                        "req_id": req_id,
                        "fingerprint": alert_data.fingerprint,
                        "previous_counter": existing_alert.counter,
                    },
                )

                # Create a new alert record (new occurrence)
                alert = Alert(
                    req_id=req_id,
                    fingerprint=alert_data.fingerprint,
                    alert_status=webhook_status,
                    processing_status="new",
                    alert_name=alert_name,
                    group_name=group_name,
                    severity=severity,
                    instance=instance,
                    prometheus=prometheus,
                    labels=alert_data.labels.model_dump(mode="json"),
                    annotations=(
                        alert_data.annotations.model_dump(mode="json")
                        if alert_data.annotations
                        else None
                    ),
                    starts_at=alert_data.startsAt,
                    ends_at=alert_data.endsAt,
                    generator_url=alert_data.generatorURL,
                    raw_data=alert_data.model_dump(mode="json"),
                    counter=existing_alert.counter + 1,  # Increment from previous
                )
                db.add(alert)
                db.flush()
                processed_alerts.append(alert)

                logger.info(
                    f"Pre-heat: Created new occurrence id={alert.id}, counter={alert.counter}",
                    extra={"req_id": req_id, "fingerprint": alert_data.fingerprint},
                )

            # Case 3: Alert exists with processing_status!="complete" AND webhook says "firing"
            # → Update counter
            elif existing_alert.processing_status != "complete" and webhook_status == "firing":
                logger.info(
                    "Pre-heat: Alert still processing, updating counter",
                    extra={
                        "req_id": req_id,
                        "fingerprint": alert_data.fingerprint,
                        "old_counter": existing_alert.counter,
                    },
                )

                existing_alert.counter += 1
                existing_alert.updated_at = datetime.utcnow()
                existing_alert.raw_data = alert_data.model_dump(mode="json")
                db.flush()
                processed_alerts.append(existing_alert)

                logger.info(
                    f"Pre-heat: Updated counter to {existing_alert.counter}",
                    extra={"req_id": req_id, "fingerprint": alert_data.fingerprint},
                )

            # Case 4: Alert exists with processing_status!="complete" AND webhook says "resolved"
            # → Update alert_status to "resolved"
            elif existing_alert.processing_status != "complete" and webhook_status == "resolved":
                logger.info(
                    "Pre-heat: Alert resolved, updating alert_status",
                    extra={
                        "req_id": req_id,
                        "fingerprint": alert_data.fingerprint,
                        "processing_status": existing_alert.processing_status,
                    },
                )

                existing_alert.alert_status = "resolved"
                existing_alert.ends_at = alert_data.endsAt
                existing_alert.updated_at = datetime.utcnow()
                existing_alert.raw_data = alert_data.model_dump(mode="json")
                db.flush()
                processed_alerts.append(existing_alert)

                logger.info(
                    "Pre-heat: Updated alert_status to resolved",
                    extra={"req_id": req_id, "fingerprint": alert_data.fingerprint},
                )

            # Case 5: Alert exists with processing_status="complete" AND webhook says "resolved"
            # → No action (alert already complete and now resolved)
            else:
                logger.info(
                    "Pre-heat: Alert complete and resolved, no action",
                    extra={
                        "req_id": req_id,
                        "fingerprint": alert_data.fingerprint,
                        "processing_status": existing_alert.processing_status,
                        "alert_status": webhook_status,
                    },
                )
                processed_alerts.append(existing_alert)

        except Exception as e:
            logger.error(
                f"Pre-heat error for fingerprint {alert_data.fingerprint}: {e}",
                exc_info=True,
                extra={"req_id": req_id},
            )
            # Continue processing other alerts
            continue

    # Commit all changes at once
    db.commit()

    return processed_alerts
