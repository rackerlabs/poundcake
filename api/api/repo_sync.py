"""API endpoints for Git-backed import/export workflows."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from api.api.auth import require_admin, require_auth_if_enabled
from api.core.database import get_db
from api.core.logging import get_logger
from api.schemas.schemas import RepoSyncResponse
from api.services.repo_sync_service import RepoSyncError, RepoSyncService

logger = get_logger(__name__)
router = APIRouter(tags=["repo-sync"])


@router.post("/repo-sync/alert-rules/export", response_model=RepoSyncResponse)
async def export_alert_rules(
    request: Request,
    _user: str | None = Depends(require_auth_if_enabled),
) -> RepoSyncResponse:
    """Export current alert rules into the configured Git repository."""
    try:
        return RepoSyncResponse.model_validate(await RepoSyncService().export_alert_rules())
    except RepoSyncError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.error(
            "Failed to export alert rules",
            extra={"req_id": request.state.req_id, "error": str(exc)},
        )
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/repo-sync/alert-rules/import", response_model=RepoSyncResponse)
async def import_alert_rules(
    request: Request,
    _user: str | None = Depends(require_auth_if_enabled),
) -> RepoSyncResponse:
    """Import alert rules from the configured Git repository."""
    try:
        return RepoSyncResponse.model_validate(await RepoSyncService().import_alert_rules())
    except RepoSyncError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.error(
            "Failed to import alert rules",
            extra={"req_id": request.state.req_id, "error": str(exc)},
        )
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.delete("/repo-sync/alert-rules", response_model=RepoSyncResponse)
async def clear_alert_rules(
    request: Request,
    _context=Depends(require_admin),
) -> RepoSyncResponse:
    """Clear all alert rules currently managed by PoundCake."""
    try:
        return RepoSyncResponse.model_validate(await RepoSyncService().clear_alert_rules())
    except RepoSyncError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.error(
            "Failed to clear alert rules",
            extra={"req_id": request.state.req_id, "error": str(exc)},
        )
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/repo-sync/workflow-actions/export", response_model=RepoSyncResponse)
async def export_workflow_actions(
    request: Request,
    db: AsyncSession = Depends(get_db),
    _user: str | None = Depends(require_auth_if_enabled),
) -> RepoSyncResponse:
    """Export current workflows and actions into the configured Git repository."""
    try:
        return RepoSyncResponse.model_validate(await RepoSyncService(db).export_workflow_actions())
    except RepoSyncError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.error(
            "Failed to export workflows and actions",
            extra={"req_id": request.state.req_id, "error": str(exc)},
        )
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/repo-sync/workflow-actions/import", response_model=RepoSyncResponse)
async def import_workflow_actions(
    request: Request,
    db: AsyncSession = Depends(get_db),
    _user: str | None = Depends(require_auth_if_enabled),
) -> RepoSyncResponse:
    """Import workflows and actions from the configured Git repository."""
    try:
        return RepoSyncResponse.model_validate(await RepoSyncService(db).import_workflow_actions())
    except RepoSyncError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.error(
            "Failed to import workflows and actions",
            extra={"req_id": request.state.req_id, "error": str(exc)},
        )
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.delete("/repo-sync/workflow-actions", response_model=RepoSyncResponse)
async def clear_workflow_actions(
    request: Request,
    db: AsyncSession = Depends(get_db),
    _context=Depends(require_admin),
) -> RepoSyncResponse:
    """Clear all user-visible workflows and actions from PoundCake."""
    try:
        return RepoSyncResponse.model_validate(await RepoSyncService(db).clear_workflow_actions())
    except RepoSyncError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.error(
            "Failed to clear workflows and actions",
            extra={"req_id": request.state.req_id, "error": str(exc)},
        )
        raise HTTPException(status_code=500, detail=str(exc)) from exc
