"""Portable workflow YAML documents for Git-backed recipe import/export."""

from __future__ import annotations

import re
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field

from api.types import JSONObject


class RepoActionReference(BaseModel):
    """Portable ingredient identity stored in exported workflow step files."""

    model_config = ConfigDict(extra="forbid")

    service_type: str = Field(..., min_length=1)
    service_exec: str = Field(..., min_length=1)
    task_key_template: str = Field(..., min_length=1)
    destination_target: str = ""


class RepoWorkflowStep(BaseModel):
    """Portable workflow step representation stored in git."""

    model_config = ConfigDict(extra="forbid")

    step_order: int = Field(..., ge=1)
    on_success: str = Field(default="continue")
    parallel_group: int = Field(default=0, ge=0)
    depth: int = Field(default=0, ge=0)
    run_phase: str = Field(default="both")
    run_condition: str = Field(default="always")
    service_payload: JSONObject | None = None
    service_exec_parameters_override: JSONObject | None = None
    action: RepoActionReference


class RepoWorkflowDocument(BaseModel):
    """Portable workflow representation stored in git."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1)
    description: str | None = None
    enabled: bool = True
    clear_timeout_sec: int | None = Field(default=None, gt=0)
    communications: JSONObject = Field(default_factory=lambda: {"mode": "inherit", "routes": []})
    recipe_ingredients: list[RepoWorkflowStep] = Field(...)


def slug_workflow_name(value: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return cleaned or "workflow"


def dump_workflow_document(document: RepoWorkflowDocument) -> str:
    return yaml.safe_dump(document.model_dump(mode="python"), sort_keys=False)


def load_workflow_document(payload: Any) -> RepoWorkflowDocument:
    if not isinstance(payload, dict):
        raise ValueError("workflow document must be a mapping")
    return RepoWorkflowDocument.model_validate(payload)


def workflow_filename(name: str) -> str:
    return f"{slug_workflow_name(name)}.yaml"
