#  ___                        _  ____      _
# |  _ \ ___  _   _ _ __   __| |/ ___|__ _| | _____
# | |_) / _ \| | | | '_ \ / _` | |   / _` | |/ / _ \
# |  __/ (_) | |_| | | | | (_| | |__| (_| |   <  __/
# |_|   \___/ \__,_|_| |_|\__,_|\____\__,_|_|\_\___|
#
"""Webhook ingestion routes."""

from fastapi import APIRouter, Depends, Body, Request
from sqlalchemy.orm import Session

from api.core.database import get_db
from api.core.logging import get_logger
from api.schemas.schemas import WebhookResponse
from api.services.pre_heat import pre_heat

router = APIRouter()
logger = get_logger(__name__)


@router.post("/webhook", response_model=WebhookResponse, status_code=202)
async def alertmanager_webhook(
    request: Request, payload: dict = Body(...), db: Session = Depends(get_db)
) -> WebhookResponse:
    """Entry point for Alertmanager webhooks. Handled by pre_heat service.

    Returns 202 Accepted - webhook received and queued for asynchronous processing.
    """
    req_id = request.state.req_id
    alert_count = len(payload.get("alerts", []))

    logger.info(
        "Received webhook from Alertmanager",
        extra={"req_id": req_id, "alert_count": alert_count},
    )

    result = pre_heat(payload, db, req_id)

    logger.info(
        "Webhook processed successfully",
        extra={
            "req_id": req_id,
            "status": result.get("status"),
            "order_id": result.get("order_id"),
        },
    )

    return WebhookResponse(
        status=result["status"],
        order_id=result.get("order_id"),
        message=f"Order {result['status']}",
    )
