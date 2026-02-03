#  ___                        _  ____      _
# |  _ \ ___  _   _ _ __   __| |/ ___|__ _| | _____
# | |_) / _ \| | | | '_ \ / _` | |   / _` | |/ / _ \
# |  __/ (_) | |_| | | | | (_| | |__| (_| |   <  __/
# |_|   \___/ \__,_|_| |_|\__,_|\____\__,_|_|\_\___|
#
"""Bridge router to proxy StackStorm actions through the API."""

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from typing import Dict, Any
from api.core.logging import get_logger
from api.schemas.schemas import ExecutionResponse
from api.services.stackstorm_service import StackStormActionManager, get_action_manager

router = APIRouter()
logger = get_logger(__name__)

@router.post("/stackstorm/execute", response_model=ExecutionResponse)
async def trigger_st2_execution(
    request: Request,
    request_data: Dict[str, Any],
    x_request_id: str = Header(None),
    manager: StackStormActionManager = Depends(get_action_manager)
) -> ExecutionResponse:
    """
    Bridge endpoint for Oven Executor.
    Proxies execution requests to StackStorm using the internal service client.
    """
    req_id = request.state.req_id
    action_ref = request_data.get("action")
    parameters = request_data.get("parameters", {})
    
    logger.info(
        "execute: Received StackStorm execution request",
        extra={"req_id": req_id, "action_ref": action_ref}
    )
    
    # Inject the Request ID for cross-system tracing
    if x_request_id:
        parameters["req_id"] = x_request_id

    if not action_ref:
        logger.warning(
            "execute: Missing action reference",
            extra={"req_id": req_id}
        )
        raise HTTPException(status_code=400, detail="Missing 'action' (action_ref) in payload")

    try:
        logger.debug(
            "execute: Calling StackStorm API",
            extra={"req_id": req_id, "action_ref": action_ref, "params": parameters}
        )
        
        # Utilize the existing async StackStormClient inside the manager
        result = await manager._client.execute_action(
            action_ref=action_ref,
            parameters=parameters
        )
        
        logger.info(
            "execute: StackStorm execution started successfully",
            extra={
                "req_id": req_id,
                "action_ref": action_ref,
                "execution_id": result.get("id")
            }
        )
        
        return ExecutionResponse(**result)
        
    except Exception as e:
        logger.error(
            "execute: StackStorm execution failed",
            extra={"req_id": req_id, "action_ref": action_ref, "error": str(e)},
            exc_info=True
        )
        # This catches StackStormError or connectivity issues
        raise HTTPException(status_code=502, detail=f"StackStorm Gateway Error: {str(e)}")
