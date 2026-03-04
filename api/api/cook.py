#  ___                        _  ____      _
# |  _ \ ___  _   _ _ __   __| |/ ___|__ _| | _____
# | |_) / _ \| | | | '_ \ / _` | |   / _` | |/ / _ \
# |  __/ (_) | |_| | | | | (_| | |__| (_| |   <  __/
# |_|   \___/ \__,_|_| |_|\__,_|\____\__,_|_|\_\___|
#
"""Cook router for execution orchestration and StackStorm tooling."""

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Dict, Any
from api.core.logging import get_logger
from api.core.config import get_settings
from api.core.database import get_db
from api.schemas.schemas import ExecuteRequest, ExecutionEnvelopeResponse
from api.services.execution_orchestrator import ExecutionOrchestrator, get_execution_orchestrator
from api.services.execution_types import ExecutionContext
from api.services.stackstorm_service import (
    StackStormActionManager,
    StackStormError,
    get_action_manager,
    register_workflow_to_st2,
)
from api.services.dishwasher_service import sync_stackstorm
from api.services.pack_sync_service import get_pack_sync_artifact_response
from api.api.auth import require_auth_if_enabled
from api.validation.execution import validate_execution_request

router = APIRouter()
logger = get_logger(__name__)


@router.post("/cook/execute", response_model=ExecutionEnvelopeResponse)
async def execute_ingredient(
    request: Request,
    payload: ExecuteRequest,
    x_request_id: str = Header(None),
    orchestrator: ExecutionOrchestrator = Depends(get_execution_orchestrator),
) -> ExecutionEnvelopeResponse:
    """
    Generic execution endpoint for all supported execution engines.
    """
    req_id = request.state.req_id
    validation_error = validate_execution_request(
        execution_engine=payload.execution_engine,
        execution_target=payload.execution_target,
        execution_payload=payload.execution_payload,
        execution_parameters=payload.execution_parameters,
        context=payload.context,
    )
    if validation_error:
        raise HTTPException(status_code=400, detail=validation_error)

    logger.info(
        "Received execution request",
        extra={
            "req_id": req_id,
            "execution_engine": payload.execution_engine,
            "execution_target": payload.execution_target,
            "method": request.method,
        },
    )

    try:
        execution_result = await orchestrator.execute(
            ExecutionContext(
                engine=payload.execution_engine,
                execution_target=payload.execution_target,
                execution_payload=payload.execution_payload,
                execution_parameters=payload.execution_parameters,
                retry_count=payload.retry_count,
                retry_delay=payload.retry_delay,
                timeout_duration_sec=payload.timeout_duration_sec,
                context=payload.context,
                req_id=req_id,
            )
        )

        logger.info(
            "Execution request completed",
            extra={
                "req_id": req_id,
                "execution_engine": execution_result.engine,
                "execution_target": payload.execution_target,
                "execution_ref": execution_result.execution_ref,
                "execution_status": execution_result.status,
                "method": request.method,
                "status_code": 200,
            },
        )

        return ExecutionEnvelopeResponse(
            execution_ref=execution_result.execution_ref,
            engine=execution_result.engine,
            status=execution_result.status,
            error_message=execution_result.error_message,
            result=execution_result.result,
            raw=execution_result.raw,
            attempts=execution_result.attempts,
        )

    except Exception as e:
        logger.error(
            "Execution request failed",
            extra={
                "req_id": req_id,
                "execution_engine": payload.execution_engine,
                "execution_target": payload.execution_target,
                "method": request.method,
                "status_code": 502,
                "error": str(e),
            },
            exc_info=True,
        )
        raise HTTPException(status_code=502, detail=f"Execution gateway error: {str(e)}")


@router.get("/cook/executions/{execution_id}")
async def get_st2_execution(
    execution_id: str,
    request: Request,
    manager: StackStormActionManager = Depends(get_action_manager),
    _user: str | None = Depends(require_auth_if_enabled),
):
    """Get a StackStorm execution by ID."""
    req_id = request.state.req_id
    try:
        result = await manager._client.get_execution(execution_id)
        return result
    except StackStormError as e:
        logger.error(
            "Failed to get StackStorm execution",
            extra={"req_id": req_id, "execution_id": execution_id, "error": str(e)},
        )
        raise HTTPException(status_code=502, detail=str(e))


@router.get("/cook/executions")
async def list_st2_executions(
    request: Request,
    parent: str | None = Query(None, description="Filter by parent execution id"),
    limit: int = Query(50, ge=1, le=1000),
    manager: StackStormActionManager = Depends(get_action_manager),
    _user: str | None = Depends(require_auth_if_enabled),
):
    """List StackStorm executions (optional parent filter)."""
    req_id = request.state.req_id
    try:
        return await manager.get_execution_history(limit=limit, parent=parent)
    except StackStormError as e:
        logger.error(
            "Failed to list StackStorm executions",
            extra={"req_id": req_id, "parent": parent, "error": str(e)},
        )
        raise HTTPException(status_code=502, detail=str(e))


@router.get("/cook/executions/{execution_id}/tasks")
async def get_st2_execution_tasks(
    execution_id: str,
    request: Request,
    manager: StackStormActionManager = Depends(get_action_manager),
    _user: str | None = Depends(require_auth_if_enabled),
):
    """Get StackStorm execution task results by ID (Orquesta)."""
    req_id = request.state.req_id
    try:
        result = await manager._client.get_execution_tasks(execution_id)
        return result
    except StackStormError as e:
        logger.error(
            "Failed to get StackStorm execution tasks",
            extra={"req_id": req_id, "execution_id": execution_id, "error": str(e)},
        )
        raise HTTPException(status_code=502, detail=str(e))


@router.put("/cook/executions/{execution_id}")
async def cancel_st2_execution(
    execution_id: str,
    request: Request,
    manager: StackStormActionManager = Depends(get_action_manager),
    _user: str | None = Depends(require_auth_if_enabled),
):
    """Cancel a StackStorm execution."""
    req_id = request.state.req_id
    try:
        ok = await manager._client.cancel_execution(execution_id)
        return {"status": "canceled" if ok else "failed", "execution_id": execution_id}
    except StackStormError as e:
        logger.error(
            "Failed to cancel StackStorm execution",
            extra={"req_id": req_id, "execution_id": execution_id, "error": str(e)},
        )
        raise HTTPException(status_code=502, detail=str(e))


@router.delete("/cook/executions/{execution_id}")
async def delete_st2_execution(
    execution_id: str,
    request: Request,
    manager: StackStormActionManager = Depends(get_action_manager),
    _user: str | None = Depends(require_auth_if_enabled),
):
    """Delete a StackStorm execution record."""
    req_id = request.state.req_id
    try:
        ok = await manager._client.delete_execution(execution_id)
        return {"status": "deleted" if ok else "failed", "execution_id": execution_id}
    except StackStormError as e:
        logger.error(
            "Failed to delete StackStorm execution",
            extra={"req_id": req_id, "execution_id": execution_id, "error": str(e)},
        )
        raise HTTPException(status_code=502, detail=str(e))


@router.post("/cook/workflows/register")
async def register_st2_workflow(
    request: Request,
    payload: Dict[str, Any],
    _user: str | None = Depends(require_auth_if_enabled),
):
    """Register an Orquesta workflow in StackStorm."""
    req_id = request.state.req_id
    settings = get_settings()
    api_key = settings.get_stackstorm_api_key()
    if not api_key:
        raise HTTPException(status_code=503, detail="StackStorm API key not available")

    try:
        workflow_id = await register_workflow_to_st2(settings.stackstorm_url, api_key, payload)
        return {"workflow_id": workflow_id}
    except ValueError as e:
        logger.warning(
            "Invalid workflow registration payload",
            extra={"req_id": req_id, "error": str(e)},
        )
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(
            "Failed to register workflow",
            extra={"req_id": req_id, "error": str(e)},
        )
        raise HTTPException(status_code=502, detail=str(e))


@router.post("/cook/sync")
async def sync_stackstorm_to_poundcake(
    request: Request,
    mark_bootstrap: bool = Query(False, description="Mark bootstrap completion"),
    _user: str | None = Depends(require_auth_if_enabled),
):
    """Sync StackStorm actions/workflows to PoundCake Ingredients/Recipes."""
    req_id = request.state.req_id
    try:
        stats = await sync_stackstorm(mark_bootstrap=mark_bootstrap)
        logger.info(
            "StackStorm sync complete",
            extra={"req_id": req_id, "stats": stats},
        )
        return stats
    except Exception as e:
        logger.error(
            "StackStorm sync failed",
            extra={"req_id": req_id, "error": str(e)},
        )
        raise HTTPException(status_code=502, detail=str(e))


@router.get("/cook/actions")
async def list_st2_actions(
    request: Request,
    pack: str | None = Query(None, description="Filter by pack name"),
    limit: int = Query(100, description="Maximum number of actions to return"),
    manager: StackStormActionManager = Depends(get_action_manager),
    _user: str | None = Depends(require_auth_if_enabled),
):
    """List available StackStorm actions."""
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
            extra={"req_id": req_id, "method": request.method, "error": str(e)},
            exc_info=True,
        )
        raise HTTPException(status_code=502, detail=f"Failed to list actions: {str(e)}")


@router.get("/cook/actions/{action_ref:path}")
async def get_st2_action(
    action_ref: str,
    request: Request,
    manager: StackStormActionManager = Depends(get_action_manager),
    _user: str | None = Depends(require_auth_if_enabled),
):
    """Get details of a specific StackStorm action."""
    req_id = request.state.req_id

    try:
        action = await manager.get_action(action_ref)
        if not action:
            raise HTTPException(status_code=404, detail=f"Action '{action_ref}' not found")

        logger.info(
            "Retrieved StackStorm action",
            extra={"req_id": req_id, "method": request.method, "action_ref": action_ref},
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


@router.get("/cook/packs")
async def get_stackstorm_pack_tgz(
    request: Request,
    db: AsyncSession = Depends(get_db),
    pack_sync_token: str | None = Header(default=None, alias="X-Pack-Sync-Token"),
):
    """Return the current generated PoundCake StackStorm pack as tar.gz."""
    return await get_pack_sync_artifact_response(
        request=request,
        db=db,
        pack_sync_token=pack_sync_token,
    )


@router.get("/cook/packs/catalog")
async def list_st2_packs(
    request: Request,
    manager: StackStormActionManager = Depends(get_action_manager),
    _user: str | None = Depends(require_auth_if_enabled),
):
    """List available StackStorm packs from StackStorm API."""
    req_id = request.state.req_id

    try:
        packs = await manager.list_packs()
        logger.info(
            "Listed StackStorm packs",
            extra={"req_id": req_id, "method": request.method, "pack_count": len(packs)},
        )
        return {"packs": packs}
    except Exception as e:
        logger.error(
            "Failed to list StackStorm packs",
            extra={"req_id": req_id, "method": request.method, "error": str(e)},
            exc_info=True,
        )
        raise HTTPException(status_code=502, detail=f"Failed to list packs: {str(e)}")
