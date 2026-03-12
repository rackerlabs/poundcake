"""API routes for global communications policy management."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.database import get_db
from api.core.logging import get_logger
from api.schemas.schemas import (
    CommunicationPolicyResponse,
    CommunicationPolicyUpdate,
    CommunicationRouteResponse,
)
from api.services.communications_policy import (
    get_global_policy_routes,
    lifecycle_summary,
    policy_has_enabled_routes,
    serialize_route,
    sync_fallback_policy_recipe,
    sync_global_policy_routes,
)

router = APIRouter()
logger = get_logger(__name__)


def _response_routes(routes: list[Any]) -> list[CommunicationRouteResponse]:
    return [CommunicationRouteResponse(**serialize_route(route)) for route in routes]


@router.get("/communications/policy", response_model=CommunicationPolicyResponse)
async def get_communications_policy(
    db: AsyncSession = Depends(get_db),
) -> CommunicationPolicyResponse:
    routes = await get_global_policy_routes(db)
    return CommunicationPolicyResponse(
        configured=policy_has_enabled_routes(routes),
        routes=_response_routes(routes),
        lifecycle_summary=lifecycle_summary(),
    )


@router.put("/communications/policy", response_model=CommunicationPolicyResponse)
async def put_communications_policy(
    request: Request,
    payload: CommunicationPolicyUpdate,
    db: AsyncSession = Depends(get_db),
) -> CommunicationPolicyResponse:
    req_id = request.state.req_id
    async with db.begin():
        routes = await sync_global_policy_routes(
            db, routes=[item.model_dump() for item in payload.routes]
        )
        await sync_fallback_policy_recipe(db, routes=routes)

    logger.info(
        "Updated global communications policy",
        extra={
            "req_id": req_id,
            "configured": policy_has_enabled_routes(routes),
            "route_count": len(routes),
        },
    )
    return CommunicationPolicyResponse(
        configured=policy_has_enabled_routes(routes),
        routes=_response_routes(routes),
        lifecycle_summary=lifecycle_summary(),
    )
