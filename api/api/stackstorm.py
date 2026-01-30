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
"""StackStorm API endpoints for action and pack management."""

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from api.api.auth import require_auth_if_enabled
from api.services.stackstorm_service import get_action_manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/stackstorm", tags=["stackstorm"])


# =============================================================================
# Pack Endpoints
# =============================================================================


@router.get("/packs")
async def list_packs(
    request: Request,
    _user: str | None = Depends(require_auth_if_enabled),
):
    """List available StackStorm packs."""
    manager = get_action_manager()
    try:
        packs = await manager.list_packs()
        return {"packs": packs}
    except Exception as e:
        logger.error("Failed to list packs: %s", str(e))
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# Action Endpoints
# =============================================================================


@router.get("/actions")
async def list_actions(
    request: Request,
    pack: str | None = None,
    limit: int = 100,
    _user: str | None = Depends(require_auth_if_enabled),
):
    """List available StackStorm actions.

    Args:
        pack: Filter by pack name
        limit: Maximum number of actions to return
    """
    manager = get_action_manager()
    try:
        actions = await manager.list_actions(pack=pack, limit=limit)
        return {"actions": actions}
    except Exception as e:
        logger.error("Failed to list actions: %s", str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/actions/{action_ref:path}")
async def get_action(
    action_ref: str,
    request: Request,
    _user: str | None = Depends(require_auth_if_enabled),
):
    """Get details of a specific action.

    Args:
        action_ref: Action reference (pack.action_name)
    """
    manager = get_action_manager()
    try:
        action = await manager.get_action(action_ref)
        if not action:
            raise HTTPException(status_code=404, detail=f"Action '{action_ref}' not found")
        return action
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to get action %s: %s", action_ref, str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/actions")
async def create_action(
    request: Request,
    action_data: dict[str, Any],
    _user: str | None = Depends(require_auth_if_enabled),
):
    """Create a new StackStorm action.

    Args:
        action_data: Action definition
    """
    manager = get_action_manager()
    try:
        result = await manager.create_action(action_data)
        if not result:
            raise HTTPException(status_code=400, detail="Failed to create action")
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to create action: %s", str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/actions/{action_ref:path}")
async def update_action(
    action_ref: str,
    request: Request,
    action_data: dict[str, Any],
    _user: str | None = Depends(require_auth_if_enabled),
):
    """Update a StackStorm action.

    Args:
        action_ref: Action reference (pack.action_name)
        action_data: Updated action definition
    """
    manager = get_action_manager()
    try:
        result = await manager.update_action(action_ref, action_data)
        if not result:
            raise HTTPException(status_code=400, detail=f"Failed to update action '{action_ref}'")
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to update action %s: %s", action_ref, str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/actions/{action_ref:path}")
async def delete_action(
    action_ref: str,
    request: Request,
    _user: str | None = Depends(require_auth_if_enabled),
):
    """Delete a StackStorm action.

    Args:
        action_ref: Action reference (pack.action_name)
    """
    manager = get_action_manager()
    try:
        success = await manager.delete_action(action_ref)
        if not success:
            raise HTTPException(status_code=400, detail=f"Failed to delete action '{action_ref}'")
        return {"status": "deleted", "action_ref": action_ref}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to delete action %s: %s", action_ref, str(e))
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# Execution Endpoints
# =============================================================================


@router.get("/executions")
async def list_executions(
    request: Request,
    limit: int = 50,
    action: str | None = None,
    _user: str | None = Depends(require_auth_if_enabled),
):
    """Get StackStorm execution history.

    Args:
        limit: Maximum number of executions
        action: Filter by action reference
    """
    manager = get_action_manager()
    try:
        executions = await manager.get_execution_history(limit=limit, action=action)
        return {"executions": executions}
    except Exception as e:
        logger.error("Failed to get executions: %s", str(e))
        raise HTTPException(status_code=500, detail=str(e))
