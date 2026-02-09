#  ___                        _  ____      _
# |  _ \ ___  _   _ _ __   __| |/ ___|__ _| | _____
# | |_) / _ \| | | | '_ \ / _` | |   / _` | |/ / _ \
# |  __/ (_) | |_| | | | | (_| | |__| (_| |   <  __/
# |_|   \___/ \__,_|_| |_|\__,_|\____\__,_|_|\_\___|
#
"""API routes for Order management."""

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List
from datetime import datetime, timezone

from api.core.database import get_db
from api.core.logging import get_logger
from api.models.models import Order
from api.schemas.schemas import OrderCreate, OrderResponse, OrderUpdate
from api.schemas.query_params import OrderQueryParams, validate_query_params

router = APIRouter()
logger = get_logger(__name__)


@router.get("/orders", response_model=List[OrderResponse])
async def fetch_orders(
    request: Request,
    params: OrderQueryParams = Depends(validate_query_params(OrderQueryParams)),
    db: AsyncSession = Depends(get_db),
):
    """
    Get orders with optional filtering.

    Query Parameters:
    - processing_status: Filter by processing status (new/pending/processing/complete/failed)
    - alert_status: Filter by alert status (firing/resolved)
    - req_id: Filter by request ID
    - group_name: Filter by group name
    - limit: Maximum number of results (default: 100, max: 1000)
    - offset: Number of results to skip (default: 0)

    Returns 422 Unprocessable Entity if unknown or invalid query parameters are provided.
    """
    request_id = request.state.req_id

    logger.debug(
        "Fetching orders",
        extra={
            "req_id": request_id,
            "processing_status": (
                params.processing_status.value if params.processing_status else None
            ),
            "alert_status": params.alert_status.value if params.alert_status else None,
            "filter_req_id": params.req_id,
            "group_name": params.group_name,
            "limit": params.limit,
            "offset": params.offset,
        },
    )

    query = select(Order)

    if params.processing_status:
        query = query.where(Order.processing_status == params.processing_status.value)
    if params.alert_status:
        query = query.where(Order.alert_status == params.alert_status.value)
    if params.req_id:
        query = query.where(Order.req_id == params.req_id)
    if params.group_name:
        query = query.where(Order.alert_group_name == params.group_name)

    query = query.order_by(Order.created_at.desc()).limit(params.limit).offset(params.offset)
    result = await db.execute(query)
    orders = result.scalars().all()

    logger.debug(
        "Orders fetched successfully",
        extra={"req_id": request_id, "count": len(orders)},
    )

    return orders


@router.post("/orders", response_model=OrderResponse, status_code=201)
async def create_order(request: Request, payload: OrderCreate, db: AsyncSession = Depends(get_db)):
    """Create an order manually (non-Alertmanager ingestion)."""
    req_id = request.state.req_id

    logger.info(
        "Creating order",
        extra={
            "req_id": req_id,
            "order_req_id": payload.req_id,
            "alert_status": payload.alert_status,
            "group_name": payload.alert_group_name,
        },
    )

    order = Order(**payload.dict())
    db.add(order)
    await db.commit()
    await db.refresh(order)

    logger.info(
        "Order created successfully",
        extra={"req_id": req_id, "order_id": order.id},
    )

    return order


@router.get("/orders/{order_id}", response_model=OrderResponse)
async def get_order(request: Request, order_id: int, db: AsyncSession = Depends(get_db)):
    """Retrieve a specific order by ID."""
    req_id = request.state.req_id

    logger.debug("Fetching order by ID", extra={"req_id": req_id, "order_id": order_id})

    result = await db.execute(select(Order).where(Order.id == order_id))
    order = result.scalars().first()

    if not order:
        logger.warning("Order not found", extra={"req_id": req_id, "order_id": order_id})
        raise HTTPException(status_code=404, detail="Order not found")

    return order


@router.put("/orders/{order_id}", response_model=OrderResponse)
async def update_order(
    request: Request, order_id: int, payload: OrderUpdate, db: AsyncSession = Depends(get_db)
):
    """Used by Timer to set status to 'complete' or Chef to 'processing'."""
    req_id = request.state.req_id

    logger.info("Updating order", extra={"req_id": req_id, "order_id": order_id})

    result = await db.execute(select(Order).where(Order.id == order_id))
    order = result.scalars().first()
    if not order:
        logger.warning(
            "Order not found for update",
            extra={"req_id": req_id, "order_id": order_id},
        )
        raise HTTPException(status_code=404, detail="Order not found")

    update_data = payload.dict(exclude_unset=True)
    for key, value in update_data.items():
        setattr(order, key, value)

    order.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(order)

    logger.info(
        "Order updated successfully",
        extra={
            "req_id": req_id,
            "order_id": order_id,
            "fields_updated": len(update_data),
            "new_status": order.processing_status,
        },
    )

    return order
