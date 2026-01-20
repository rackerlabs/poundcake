"""Mappings API endpoints for alert-to-action mapping management."""

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from api.api.auth import require_auth_if_enabled
from api.core.database import get_db
from api.services.mapping_service import MappingService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/mappings", tags=["mappings"])


# =============================================================================
# Pydantic Models
# =============================================================================


class MappingCreate(BaseModel):
    """Request model for creating a mapping."""

    alert_name: str
    config: dict[str, Any]
    handler: str = "yaml_config"
    description: str | None = None


class MappingUpdate(BaseModel):
    """Request model for updating a mapping."""

    config: dict[str, Any] | None = None
    handler: str | None = None
    description: str | None = None
    enabled: bool | None = None


class MappingImport(BaseModel):
    """Request model for importing mappings."""

    yaml_content: str
    overwrite: bool = False


# =============================================================================
# Endpoints
# =============================================================================


@router.get("")
async def list_mappings(
    request: Request,
    db: Session = Depends(get_db),
    _user: str | None = Depends(require_auth_if_enabled),
):
    """List all mappings."""
    mappings = MappingService.list_mappings(db)
    return {"mappings": mappings}


@router.get("/export")
async def export_mappings(
    request: Request,
    db: Session = Depends(get_db),
    _user: str | None = Depends(require_auth_if_enabled),
):
    """Export all mappings as YAML."""
    yaml_content = MappingService.export_mappings(db)
    return PlainTextResponse(
        content=yaml_content,
        media_type="application/x-yaml",
        headers={"Content-Disposition": "attachment; filename=mappings.yaml"},
    )


@router.post("/import")
async def import_mappings(
    request: Request,
    data: MappingImport,
    db: Session = Depends(get_db),
    user: str | None = Depends(require_auth_if_enabled),
):
    """Import mappings from YAML content."""
    try:
        result = MappingService.import_mappings(
            db,
            data.yaml_content,
            overwrite=data.overwrite,
            imported_by=user,
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{alert_name}")
async def get_mapping(
    alert_name: str,
    request: Request,
    db: Session = Depends(get_db),
    _user: str | None = Depends(require_auth_if_enabled),
):
    """Get a specific mapping by alert name."""
    mapping = MappingService.get_mapping(db, alert_name)
    if not mapping:
        raise HTTPException(status_code=404, detail=f"Mapping for '{alert_name}' not found")
    return {"alert_name": alert_name, "config": mapping}


@router.post("")
async def create_mapping(
    request: Request,
    data: MappingCreate,
    db: Session = Depends(get_db),
    user: str | None = Depends(require_auth_if_enabled),
):
    """Create a new mapping."""
    try:
        result = MappingService.create_mapping(
            db,
            alert_name=data.alert_name,
            config=data.config,
            handler=data.handler,
            description=data.description,
            created_by=user,
        )
        return {"status": "created", "alert_name": data.alert_name, "mapping": result}
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.put("/{alert_name}")
async def update_mapping(
    alert_name: str,
    request: Request,
    data: MappingUpdate,
    db: Session = Depends(get_db),
    user: str | None = Depends(require_auth_if_enabled),
):
    """Update an existing mapping."""
    try:
        result = MappingService.update_mapping(
            db,
            alert_name=alert_name,
            config=data.config,
            handler=data.handler,
            description=data.description,
            enabled=data.enabled,
            updated_by=user,
        )
        return {"status": "updated", "alert_name": alert_name, "mapping": result}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/{alert_name}")
async def delete_mapping(
    alert_name: str,
    request: Request,
    db: Session = Depends(get_db),
    _user: str | None = Depends(require_auth_if_enabled),
):
    """Delete a mapping."""
    deleted = MappingService.delete_mapping(db, alert_name)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Mapping for '{alert_name}' not found")
    return {"status": "deleted", "alert_name": alert_name}


@router.post("/{alert_name}/toggle")
async def toggle_mapping(
    alert_name: str,
    request: Request,
    enabled: bool = True,
    db: Session = Depends(get_db),
    _user: str | None = Depends(require_auth_if_enabled),
):
    """Toggle a mapping's enabled status."""
    try:
        result = MappingService.toggle_mapping(db, alert_name, enabled)
        return {"status": "toggled", **result}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
