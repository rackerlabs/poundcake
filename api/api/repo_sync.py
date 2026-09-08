"""API endpoints for Git-backed workflow import/export."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.api.auth import require_admin, require_operator
from api.api.recipes import create_recipe, update_recipe
from api.core.database import get_db
from api.core.logging import get_logger
from api.core.time import utc_now_db
from api.models.models import Recipe
from api.schemas.schemas import DeleteResponse, RecipeUpdate, RepoSyncResponse
from api.services.communications_policy import is_hidden_workflow_recipe
from api.services.workflow_repo_sync import (
    WorkflowRepoSyncError,
    export_workflows,
    import_workflows,
)

logger = get_logger(__name__)
router = APIRouter(tags=["repo-sync"])


@router.post("/repo-sync/workflows/export", response_model=RepoSyncResponse)
async def export_workflow_repo(
    request: Request,
    db: AsyncSession = Depends(get_db),
    _context: object = Depends(require_operator),
) -> RepoSyncResponse:
    try:
        return await export_workflows(db)
    except WorkflowRepoSyncError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.error(
            "Failed to export workflows",
            extra={"req_id": request.state.req_id, "error": str(exc)},
        )
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/repo-sync/workflows/import", response_model=RepoSyncResponse)
async def import_workflow_repo(
    request: Request,
    db: AsyncSession = Depends(get_db),
    _context: object = Depends(require_operator),
) -> RepoSyncResponse:
    try:
        summary, payloads = await import_workflows(db)
    except WorkflowRepoSyncError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    created = 0
    updated = 0
    for payload in payloads:
        result = await db.execute(select(Recipe).where(Recipe.name == payload.name))
        existing = result.scalars().first()
        if existing is None:
            await create_recipe(request=request, recipe=payload, db=db, _context=_context)
            created += 1
            continue
        await update_recipe(
            request=request,
            recipe_id=existing.id,
            payload=RecipeUpdate(
                description=payload.description,
                enabled=payload.enabled,
                clear_timeout_sec=payload.clear_timeout_sec,
                recipe_ingredients=payload.recipe_ingredients,
                communications=payload.communications,
            ),
            db=db,
            _context=_context,
        )
        updated += 1
    imported = dict(summary.imported or {})
    imported["created"] = created
    imported["updated"] = updated
    summary.imported = imported
    summary.message = f"Imported {created} new and {updated} updated workflow(s)."
    return summary


@router.delete("/repo-sync/workflows", response_model=DeleteResponse)
async def clear_user_workflows(
    request: Request,
    db: AsyncSession = Depends(get_db),
    _context: object = Depends(require_admin),
) -> DeleteResponse:
    result = await db.execute(select(Recipe))
    recipes = [row for row in result.scalars().all() if not is_hidden_workflow_recipe(row)]
    disabled = 0
    async with db.begin():
        for recipe in recipes:
            if recipe.enabled:
                recipe.enabled = False
                recipe.updated_at = utc_now_db()
                disabled += 1
    logger.info(
        "Disabled user workflows",
        extra={"req_id": request.state.req_id, "disabled": disabled},
    )
    return DeleteResponse(
        status="disabled",
        id=0,
        message=f"Disabled {disabled} user-facing workflow(s).",
    )
