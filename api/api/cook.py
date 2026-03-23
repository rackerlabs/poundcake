#  ___                        _  ____      _
# |  _ \ ___  _   _ _ __   __| |/ ___|__ _| | _____
# | |_) / _ \| | | | '_ \ / _` | |   / _` | |/ / _ \
# |  __/ (_) | |_| | | | | (_| | |__| (_| |   <  __/
# |_|   \___/ \__,_|_| |_|\__,_|\____\__,_|_|\_\___|
#
"""Cook router for execution orchestration and StackStorm tooling."""

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Query
from sqlalchemy.ext.asyncio import AsyncSession
from api.core.logging import get_logger
from api.core.config import get_settings
from api.core.database import get_db
from api.schemas.schemas import (
    ExecuteRequest,
    ExecutionEnvelopeResponse,
    StackStormExecutionListResponse,
    StackStormExecutionMutationResponse,
    StackStormExecutionResponse,
    StackStormExecutionTasksResponse,
    StackStormSyncResponse,
    StackStormWorkflowRegistrationRequest,
    StackStormWorkflowRegistrationResponse,
)
from api.services.execution_orchestrator import ExecutionOrchestrator, get_execution_orchestrator
from api.services.execution_types import ExecutionContext
from api.services.bakery_payloads import resolve_bakery_payload
from api.services.communications import (
    normalize_communication_operation,
    normalize_destination_target,
)
from api.services.communication_canonical import build_canonical_communication_context
from api.services.order_communications import apply_execution_result, prepare_communication_context
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
    db: AsyncSession = Depends(get_db),
    orchestrator: ExecutionOrchestrator = Depends(get_execution_orchestrator),
) -> ExecutionEnvelopeResponse:
    """
    Generic execution endpoint for all supported execution engines.
    """
    req_id = request.state.req_id
    try:
        execution_payload = (
            dict(payload.execution_payload) if isinstance(payload.execution_payload, dict) else {}
        )
        execution_parameters = (
            dict(payload.execution_parameters)
            if isinstance(payload.execution_parameters, dict)
            else {}
        )
        context = dict(payload.context) if isinstance(payload.context, dict) else {}

        order_id_raw = context.get("order_id")
        order_id = (
            order_id_raw
            if isinstance(order_id_raw, int)
            else (
                int(order_id_raw)
                if isinstance(order_id_raw, str) and order_id_raw.isdigit()
                else None
            )
        )
        destination_target = normalize_destination_target(
            context.get("destination_target")
            or ((resolve_bakery_payload(execution_payload).get("context") or {}).get("destination_target"))
        )
        operation = normalize_communication_operation(execution_parameters.get("operation"))
        order = None

        if payload.execution_engine == "bakery":
            payload_context_overlay: dict[str, Any] = {
                "provider_type": payload.execution_target,
                "destination_target": destination_target,
            }

            if order_id is not None:
                async with db.begin():
                    order, communication = await prepare_communication_context(
                        db,
                        order_id=order_id,
                        execution_target=payload.execution_target,
                        destination_target=destination_target,
                        operation=operation,
                    )
                    if communication.bakery_ticket_id:
                        context["bakery_ticket_id"] = communication.bakery_ticket_id
                        context["ticket_id"] = communication.bakery_ticket_id
                    context["destination_target"] = destination_target
                    context["communication_reuse_mode"] = (
                        "reopen" if communication.reopenable else "reuse"
                    )
                    payload_context_overlay["communication_reuse_mode"] = context[
                        "communication_reuse_mode"
                    ]

            execution_payload = resolve_bakery_payload(
                execution_payload,
                runtime_overlay={"context": payload_context_overlay},
            )
            payload_context = (
                dict(execution_payload.get("context"))
                if isinstance(execution_payload.get("context"), dict)
                else {}
            )
            if order is not None:
                payload_context["_canonical"] = build_canonical_communication_context(
                    order=order,
                    execution_target=payload.execution_target,
                    destination_target=destination_target,
                    operation=operation,
                    execution_payload={
                        **execution_payload,
                        "context": payload_context,
                    },
                )
            execution_payload["context"] = payload_context

        validation_error = validate_execution_request(
            execution_engine=payload.execution_engine,
            execution_target=payload.execution_target,
            execution_payload=execution_payload,
            execution_parameters=execution_parameters,
            context=context,
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

        execution_result = await orchestrator.execute(
            ExecutionContext(
                engine=payload.execution_engine,
                execution_target=payload.execution_target,
                execution_payload=execution_payload,
                execution_parameters=execution_parameters,
                retry_count=payload.retry_count,
                retry_delay=payload.retry_delay,
                timeout_duration_sec=payload.timeout_duration_sec,
                context=context,
                req_id=req_id,
            )
        )

        if payload.execution_engine == "bakery" and order_id is not None:
            async with db.begin():
                await apply_execution_result(
                    db,
                    order_id=order_id,
                    execution_target=payload.execution_target,
                    destination_target=destination_target,
                    operation=operation,
                    execution_ref=execution_result.execution_ref,
                    status=execution_result.status,
                    result_payload=execution_result.raw or execution_result.result,
                    context_updates=execution_result.context_updates,
                    error_message=execution_result.error_message,
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

    except HTTPException:
        raise
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


@router.get("/cook/executions/{execution_id}", response_model=StackStormExecutionResponse)
async def get_st2_execution(
    execution_id: str,
    request: Request,
    manager: StackStormActionManager = Depends(get_action_manager),
    _user: str | None = Depends(require_auth_if_enabled),
) -> StackStormExecutionResponse:
    """Get a StackStorm execution by ID."""
    req_id = request.state.req_id
    try:
        result = await manager._client.get_execution(execution_id)
        return StackStormExecutionResponse(root=result)
    except StackStormError as e:
        logger.error(
            "Failed to get StackStorm execution",
            extra={"req_id": req_id, "execution_id": execution_id, "error": str(e)},
        )
        raise HTTPException(status_code=502, detail=str(e))


@router.get("/cook/executions", response_model=StackStormExecutionListResponse)
async def list_st2_executions(
    request: Request,
    parent: str | None = Query(None, description="Filter by parent execution id"),
    limit: int = Query(50, ge=1, le=1000),
    manager: StackStormActionManager = Depends(get_action_manager),
    _user: str | None = Depends(require_auth_if_enabled),
) -> StackStormExecutionListResponse:
    """List StackStorm executions (optional parent filter)."""
    req_id = request.state.req_id
    try:
        return StackStormExecutionListResponse(
            root=await manager.get_execution_history(limit=limit, parent=parent)
        )
    except StackStormError as e:
        logger.error(
            "Failed to list StackStorm executions",
            extra={"req_id": req_id, "parent": parent, "error": str(e)},
        )
        raise HTTPException(status_code=502, detail=str(e))


@router.get(
    "/cook/executions/{execution_id}/tasks", response_model=StackStormExecutionTasksResponse
)
async def get_st2_execution_tasks(
    execution_id: str,
    request: Request,
    manager: StackStormActionManager = Depends(get_action_manager),
    _user: str | None = Depends(require_auth_if_enabled),
) -> StackStormExecutionTasksResponse:
    """Get StackStorm execution task results by ID (Orquesta)."""
    req_id = request.state.req_id
    try:
        result = await manager._client.get_execution_tasks(execution_id)
        return StackStormExecutionTasksResponse(root=result)
    except StackStormError as e:
        logger.error(
            "Failed to get StackStorm execution tasks",
            extra={"req_id": req_id, "execution_id": execution_id, "error": str(e)},
        )
        raise HTTPException(status_code=502, detail=str(e))


@router.put("/cook/executions/{execution_id}", response_model=StackStormExecutionMutationResponse)
async def cancel_st2_execution(
    execution_id: str,
    request: Request,
    manager: StackStormActionManager = Depends(get_action_manager),
    _user: str | None = Depends(require_auth_if_enabled),
) -> StackStormExecutionMutationResponse:
    """Cancel a StackStorm execution."""
    req_id = request.state.req_id
    try:
        ok = await manager._client.cancel_execution(execution_id)
        return StackStormExecutionMutationResponse(
            status="canceled" if ok else "failed",
            execution_id=execution_id,
        )
    except StackStormError as e:
        logger.error(
            "Failed to cancel StackStorm execution",
            extra={"req_id": req_id, "execution_id": execution_id, "error": str(e)},
        )
        raise HTTPException(status_code=502, detail=str(e))


@router.delete(
    "/cook/executions/{execution_id}", response_model=StackStormExecutionMutationResponse
)
async def delete_st2_execution(
    execution_id: str,
    request: Request,
    manager: StackStormActionManager = Depends(get_action_manager),
    _user: str | None = Depends(require_auth_if_enabled),
) -> StackStormExecutionMutationResponse:
    """Delete a StackStorm execution record."""
    req_id = request.state.req_id
    try:
        ok = await manager._client.delete_execution(execution_id)
        return StackStormExecutionMutationResponse(
            status="deleted" if ok else "failed",
            execution_id=execution_id,
        )
    except StackStormError as e:
        logger.error(
            "Failed to delete StackStorm execution",
            extra={"req_id": req_id, "execution_id": execution_id, "error": str(e)},
        )
        raise HTTPException(status_code=502, detail=str(e))


@router.post("/cook/workflows/register", response_model=StackStormWorkflowRegistrationResponse)
async def register_st2_workflow(
    request: Request,
    payload: StackStormWorkflowRegistrationRequest,
    _user: str | None = Depends(require_auth_if_enabled),
) -> StackStormWorkflowRegistrationResponse:
    """Register an Orquesta workflow in StackStorm."""
    req_id = request.state.req_id
    settings = get_settings()
    api_key = settings.get_stackstorm_api_key()
    if not api_key:
        raise HTTPException(status_code=503, detail="StackStorm API key not available")

    try:
        workflow_id = await register_workflow_to_st2(
            settings.stackstorm_url,
            api_key,
            payload.root,
        )
        return StackStormWorkflowRegistrationResponse(workflow_id=workflow_id)
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


@router.post("/cook/sync", response_model=StackStormSyncResponse)
async def sync_stackstorm_to_poundcake(
    request: Request,
    mark_bootstrap: bool = Query(False, description="Mark bootstrap completion"),
    _user: str | None = Depends(require_auth_if_enabled),
) -> StackStormSyncResponse:
    """Sync StackStorm actions/workflows to PoundCake Ingredients/Recipes."""
    req_id = request.state.req_id
    try:
        stats = await sync_stackstorm(mark_bootstrap=mark_bootstrap)
        logger.info(
            "StackStorm sync complete",
            extra={"req_id": req_id, "stats": stats},
        )
        return StackStormSyncResponse.model_validate(stats)
    except Exception as e:
        logger.error(
            "StackStorm sync failed",
            extra={"req_id": req_id, "error": str(e)},
        )
        raise HTTPException(status_code=502, detail=str(e))


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
