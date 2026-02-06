#  ___                        _  ____      _
# |  _ \ ___  _   _ _ __   __| |/ ___|__ _| | _____
# | |_) / _ \| | | | '_ \ / _` | |   / _` | |/ / _ \
# |  __/ (_) | |_| | | | | (_| | |__| (_| |   <  __/
# |_|   \___/ \__,_|_| |_|\__,_|\____\__,_|_|\_\___|
#
"""Bridge router to proxy StackStorm actions through the API."""

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Query
from typing import Dict, Any
from api.core.logging import get_logger
from api.schemas.schemas import ExecutionResponse
from api.services.stackstorm_service import StackStormActionManager, get_action_manager
from api.api.auth import require_auth_if_enabled

router = APIRouter()
logger = get_logger(__name__)


@router.post("/stackstorm/execute", response_model=ExecutionResponse)
async def trigger_st2_execution(
    request: Request,
    request_data: Dict[str, Any],
    x_request_id: str = Header(None),
    manager: StackStormActionManager = Depends(get_action_manager),
) -> ExecutionResponse:
    """
    Bridge endpoint for Oven Executor.
    Proxies execution requests to StackStorm using the internal service client.
    """
    req_id = request.state.req_id
    action_ref = request_data.get("action")
    parameters = request_data.get("parameters", {})

    logger.info(
        "Received StackStorm execution request",
        extra={"req_id": req_id, "action_ref": action_ref, "method": request.method},
    )

    if not action_ref:
        logger.warning(
            "Missing action reference",
            extra={"req_id": req_id, "method": request.method, "status_code": 400},
        )
        raise HTTPException(status_code=400, detail="Missing 'action' (action_ref) in payload")

    try:
        logger.debug(
            "Calling StackStorm API",
            extra={
                "req_id": req_id,
                "action_ref": action_ref,
                "method": request.method,
                "params": parameters,
            },
        )

        # Utilize the existing async StackStormClient inside the manager
        result = await manager._client.execute_action(
            req_id=req_id, action_ref=action_ref, parameters=parameters
        )

        logger.info(
            "StackStorm execution started successfully",
            extra={
                "req_id": req_id,
                "action_ref": action_ref,
                "method": request.method,
                "status_code": 200,
                "execution_id": result.get("id"),
            },
        )

        return ExecutionResponse(**result)

    except Exception as e:
        logger.error(
            "StackStorm execution failed",
            extra={
                "req_id": req_id,
                "action_ref": action_ref,
                "method": request.method,
                "status_code": 502,
                "error": str(e),
            },
            exc_info=True,
        )
        # This catches StackStormError or connectivity issues
        raise HTTPException(status_code=502, detail=f"StackStorm Gateway Error: {str(e)}")


@router.get("/stackstorm/actions")
async def list_st2_actions(
    request: Request,
    pack: str | None = Query(None, description="Filter by pack name"),
    limit: int = Query(100, description="Maximum number of actions to return"),
    manager: StackStormActionManager = Depends(get_action_manager),
    _user: str | None = Depends(require_auth_if_enabled),
):
    """List available StackStorm actions.

    Args:
        pack: Optional pack name to filter actions
        limit: Maximum number of actions to return

    Returns:
        List of StackStorm action definitions
    """
    req_id = request.state.req_id

    try:
        actions = await manager.list_actions(pack=pack, limit=limit)
        logger.info(
            "Listed StackStorm actions",
            extra={
                "req_id": req_id,
                "method": request.method,
                "action_count": len(actions),
                "pack": pack,
            },
        )
        return {"actions": actions}
    except Exception as e:
        logger.error(
            "Failed to list StackStorm actions",
            extra={
                "req_id": req_id,
                "method": request.method,
                "error": str(e),
            },
            exc_info=True,
        )
        raise HTTPException(status_code=502, detail=f"Failed to list actions: {str(e)}")


@router.get("/stackstorm/actions/{action_ref:path}")
async def get_st2_action(
    action_ref: str,
    request: Request,
    manager: StackStormActionManager = Depends(get_action_manager),
    _user: str | None = Depends(require_auth_if_enabled),
):
    """Get details of a specific StackStorm action.

    Args:
        action_ref: The action reference (pack.action_name)

    Returns:
        Action definition details
    """
    req_id = request.state.req_id

    try:
        action = await manager.get_action(action_ref)
        if not action:
            raise HTTPException(status_code=404, detail=f"Action '{action_ref}' not found")

        logger.info(
            "Retrieved StackStorm action",
            extra={
                "req_id": req_id,
                "method": request.method,
                "action_ref": action_ref,
            },
        )
        return action
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "Failed to get StackStorm action",
            extra={
                "req_id": req_id,
                "method": request.method,
                "action_ref": action_ref,
                "error": str(e),
            },
            exc_info=True,
        )
        raise HTTPException(status_code=502, detail=f"Failed to get action: {str(e)}")


@router.get("/stackstorm/packs")
async def list_st2_packs(
    request: Request,
    manager: StackStormActionManager = Depends(get_action_manager),
    _user: str | None = Depends(require_auth_if_enabled),
):
    """List available StackStorm packs.

    Returns:
        List of StackStorm pack definitions
    """
    req_id = request.state.req_id

    try:
        packs = await manager.list_packs()
        logger.info(
            "Listed StackStorm packs",
            extra={
                "req_id": req_id,
                "method": request.method,
                "pack_count": len(packs),
            },
        )
        return {"packs": packs}
    except Exception as e:
        logger.error(
            "Failed to list StackStorm packs",
            extra={
                "req_id": req_id,
                "method": request.method,
                "error": str(e),
            },
            exc_info=True,
        )
        raise HTTPException(status_code=502, detail=f"Failed to list packs: {str(e)}")
