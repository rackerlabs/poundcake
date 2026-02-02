#  ___                        _  ____      _
# |  _ \ ___  _   _ _ __   __| |/ ___|__ _| | _____
# | |_) / _ \| | | | '_ \ / _` | |   / _` | |/ / _ \
# |  __/ (_) | |_| | | | | (_| | |__| (_| |   <  __/
# |_|   \___/ \__,_|_| |_|\__,_|\____\__,_|_|\_\___|
#
"""Bridge router to proxy StackStorm actions through the API."""

from fastapi import APIRouter, Depends, Header, HTTPException
from typing import Dict, Any
from api.services.stackstorm_service import StackStormActionManager, get_action_manager

router = APIRouter()

@router.post("/execute")
async def trigger_st2_execution(
    request_data: Dict[str, Any],
    x_request_id: str = Header(None),
    manager: StackStormActionManager = Depends(get_action_manager)
):
    """
    Bridge endpoint for Oven Executor.
    Proxies execution requests to StackStorm using the internal service client.
    """
    action_ref = request_data.get("action")
    parameters = request_data.get("parameters", {})
    
    # Inject the Request ID for cross-system tracing
    if x_request_id:
        parameters["req_id"] = x_request_id

    if not action_ref:
        raise HTTPException(status_code=400, detail="Missing 'action' (action_ref) in payload")

    try:
        # Utilize the existing async StackStormClient inside the manager
        # We call the client directly for the specific execution
        result = await manager._client.execute_action(
            action_ref=action_ref,
            parameters=parameters
        )
        return result
    except Exception as e:
        # This catches StackStormError or connectivity issues
        raise HTTPException(status_code=502, detail=f"StackStorm Gateway Error: {str(e)}")
