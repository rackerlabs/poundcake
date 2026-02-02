#  ____                        _  ____      _
# |  _ \ ___  _   _ _ __   __| |/ ___|__ _| | _____
# | |_) / _ \| | | | '_ \ / _` | |   / _` | |/ / _ \
# |  __/ (_) | |_| | | | | (_| | |__| (_| |   <  __/
# |_|   \___/ \__,_|_| |_|\__,_|\____\__,_|_|\_\___|
#
"""Pre-heat service - creates ovens from alert group_name matching recipe."""

from sqlalchemy.orm import Session
from datetime import datetime, timezone
from api.models.models import Alert
from api.core.logging import get_logger

logger = get_logger(__name__)


def pre_heat(payload: dict, db: Session) -> dict:
    """
    Intake Handler: Solely responsible for Alert table management.
    """
    fingerprint = payload.get("fingerprint")
    alert_status = payload.get("status")  # firing or resolved

    existing = (
        db.query(Alert)
        .filter(Alert.fingerprint == fingerprint, Alert.processing_status != "complete")
        .first()
    )

    if alert_status == "firing":
        if not existing:
            # Create fresh record; status 'new' triggers the Oven Service later
            new_alert = Alert(
                fingerprint=fingerprint,
                alert_name=payload.get("labels", {}).get("alertname", "Unknown"),
                group_name=payload.get("labels", {}).get("alertname"),  # Recipe Match Key
                state="firing",
                processing_status="new",
                counter=1,
                req_id=fingerprint,  # Trace ID
            )
            db.add(new_alert)
            db.commit()
            logger.info("New alert queued", extra={"alert_id": new_alert.id})
            return {"status": "created", "alert_id": new_alert.id}
        else:
            existing.counter += 1
            db.commit()
            return {"status": "counter_incremented", "alert_id": existing.id}

    elif alert_status == "resolved" and existing:
        existing.state = "resolved"
        db.commit()
        return {"status": "state_updated", "alert_id": existing.id}

    return {"status": "ignored"}
