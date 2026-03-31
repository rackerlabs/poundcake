"""Git-backed import/export helpers for alert rules, workflows, and actions."""

from __future__ import annotations

import json
import re
from pathlib import Path, PurePosixPath
from types import SimpleNamespace
from typing import Any

import yaml
from pydantic import BaseModel as PydanticBaseModel, ConfigDict, Field
from sqlalchemy import not_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from api.api.ingredients import (
    create_ingredient,
    delete_ingredient,
    update_ingredient,
)
from api.api.recipes import (
    create_recipe,
    delete_recipe,
    update_recipe,
)
from api.core.config import get_settings
from api.core.logging import get_logger
from api.models.models import Ingredient, Recipe, RecipeIngredient
from api.schemas.schemas import (
    IngredientCreate,
    IngredientUpdate,
    RecipeCreate,
    RecipeUpdate,
)
from api.services.communications_policy import (
    MANAGED_TASK_PREFIX,
    get_recipe_local_routes,
    get_visible_recipe_steps,
    is_hidden_workflow_recipe,
)
from api.services.git_manager import get_git_manager
from api.services.prometheus_crd_manager import get_prometheus_crd_manager
from api.services.prometheus_rule_manager import (
    get_prometheus_rule_manager,
    normalize_rule_data,
    sanitize_crd_name,
)
from api.services.prometheus_service import get_prometheus_client

logger = get_logger(__name__)

REPO_SYNC_REQ_ID = "SYSTEM-REPO-SYNC"
REPO_FILE_SUFFIXES = {".yaml", ".yml", ".json"}


class BaseModel(PydanticBaseModel):
    """Strict base model for repo-sync documents owned by PoundCake."""

    model_config = ConfigDict(extra="forbid")


class RepoSyncError(RuntimeError):
    """Raised when repo sync cannot complete with the current configuration or payload."""


class RepoActionReference(BaseModel):
    """Portable action identity stored in exported workflow step files."""

    task_key_template: str = Field(..., min_length=1)
    execution_target: str = Field(..., min_length=1)
    destination_target: str = ""
    execution_engine: str = Field(..., min_length=1)


class RepoWorkflowStep(BaseModel):
    """Portable workflow step representation stored in git."""

    step_order: int = Field(..., ge=1)
    on_success: str = Field(default="continue")
    parallel_group: int = Field(default=0, ge=0)
    depth: int = Field(default=0, ge=0)
    execution_payload_override: dict[str, Any] | None = None
    execution_parameters_override: dict[str, Any] | None = None
    expected_duration_sec_override: int | None = Field(default=None, gt=0)
    timeout_duration_sec_override: int | None = Field(default=None, gt=0)
    run_phase: str = Field(default="both")
    run_condition: str = Field(default="always")
    action: RepoActionReference


class RepoWorkflowDocument(BaseModel):
    """Portable workflow representation stored in git."""

    name: str = Field(..., min_length=1)
    description: str | None = None
    enabled: bool = True
    clear_timeout_sec: int | None = Field(default=None, gt=0)
    communications: dict[str, Any] = Field(
        default_factory=lambda: {"mode": "inherit", "routes": []}
    )
    recipe_ingredients: list[RepoWorkflowStep] = Field(...)


def _fake_request(req_id: str = REPO_SYNC_REQ_ID) -> Any:
    return SimpleNamespace(state=SimpleNamespace(req_id=req_id))


def _slug(value: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return cleaned or "item"


def _normalize_repo_directory(value: str, *, label: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        raise RepoSyncError(f"{label} directory is not configured")
    path = PurePosixPath(raw)
    if path.is_absolute() or ".." in path.parts:
        raise RepoSyncError(f"{label} directory must be a relative repo path")
    normalized = str(path).strip("/")
    if not normalized or normalized == ".":
        raise RepoSyncError(f"{label} directory must not be empty")
    return normalized


def _load_repo_document(path: Path) -> Any:
    if path.suffix.lower() == ".json":
        return json.loads(path.read_text(encoding="utf-8"))
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _yaml_text(payload: dict[str, Any]) -> str:
    return yaml.safe_dump(payload, sort_keys=False)


def _action_identity(
    *,
    task_key_template: str,
    execution_target: str,
    destination_target: str,
    execution_engine: str,
) -> tuple[str, str, str, str]:
    return (
        execution_engine.strip().lower(),
        execution_target.strip(),
        destination_target.strip(),
        task_key_template.strip(),
    )


def _action_identity_from_record(action: Any) -> tuple[str, str, str, str]:
    return _action_identity(
        task_key_template=str(getattr(action, "task_key_template", "") or ""),
        execution_target=str(getattr(action, "execution_target", "") or ""),
        destination_target=str(getattr(action, "destination_target", "") or ""),
        execution_engine=str(getattr(action, "execution_engine", "") or ""),
    )


def _action_identity_from_payload(payload: dict[str, Any]) -> tuple[str, str, str, str]:
    return _action_identity(
        task_key_template=str(payload.get("task_key_template") or ""),
        execution_target=str(payload.get("execution_target") or ""),
        destination_target=str(payload.get("destination_target") or ""),
        execution_engine=str(payload.get("execution_engine") or ""),
    )


def _action_file_name(action: Any) -> str:
    destination = str(getattr(action, "destination_target", "") or "") or "default"
    return (
        f"{_slug(str(getattr(action, 'task_key_template', '') or 'action'))}"
        f"--{_slug(str(getattr(action, 'execution_engine', '') or 'engine'))}"
        f"--{_slug(str(getattr(action, 'execution_target', '') or 'target'))}"
        f"--{_slug(destination)}.yaml"
    )


def _workflow_file_name(recipe: Any) -> str:
    return f"{_slug(str(getattr(recipe, 'name', '') or 'workflow'))}.yaml"


def _action_export_payload(action: Any) -> dict[str, Any]:
    return {
        "version": 1,
        "kind": "action",
        "action": IngredientCreate.model_validate(
            {
                "execution_target": getattr(action, "execution_target", ""),
                "destination_target": getattr(action, "destination_target", "") or "",
                "task_key_template": getattr(action, "task_key_template", ""),
                "execution_id": getattr(action, "execution_id", None),
                "execution_payload": getattr(action, "execution_payload", None),
                "execution_parameters": getattr(action, "execution_parameters", None),
                "execution_engine": getattr(action, "execution_engine", ""),
                "execution_purpose": getattr(action, "execution_purpose", ""),
                "is_default": bool(getattr(action, "is_default", False)),
                "is_active": bool(getattr(action, "is_active", True)),
                "is_blocking": bool(getattr(action, "is_blocking", True)),
                "expected_duration_sec": int(getattr(action, "expected_duration_sec", 1) or 1),
                "timeout_duration_sec": int(getattr(action, "timeout_duration_sec", 300) or 300),
                "retry_count": int(getattr(action, "retry_count", 0) or 0),
                "retry_delay": int(getattr(action, "retry_delay", 5) or 0),
                "on_failure": getattr(action, "on_failure", "stop"),
            }
        ).model_dump(exclude_none=True),
    }


def _workflow_export_payload(recipe: Any) -> dict[str, Any]:
    local_routes = get_recipe_local_routes(recipe)
    communications = {
        "mode": "local" if local_routes else "inherit",
        "routes": [
            {
                "id": route.id,
                "label": route.label,
                "execution_target": route.execution_target,
                "destination_target": route.destination_target,
                "provider_config": route.provider_config,
                "enabled": route.enabled,
                "position": route.position,
            }
            for route in local_routes
        ],
    }

    steps: list[dict[str, Any]] = []
    for step in get_visible_recipe_steps(recipe):
        if step.ingredient is None:
            continue
        steps.append(
            RepoWorkflowStep.model_validate(
                {
                    "step_order": step.step_order,
                    "on_success": step.on_success,
                    "parallel_group": step.parallel_group,
                    "depth": step.depth,
                    "execution_payload_override": getattr(step, "execution_payload_override", None),
                    "execution_parameters_override": getattr(
                        step, "execution_parameters_override", None
                    ),
                    "expected_duration_sec_override": getattr(
                        step, "expected_duration_sec_override", None
                    ),
                    "timeout_duration_sec_override": getattr(
                        step, "timeout_duration_sec_override", None
                    ),
                    "run_phase": step.run_phase,
                    "run_condition": step.run_condition,
                    "action": {
                        "task_key_template": step.ingredient.task_key_template,
                        "execution_target": step.ingredient.execution_target,
                        "destination_target": step.ingredient.destination_target or "",
                        "execution_engine": step.ingredient.execution_engine,
                    },
                }
            ).model_dump(exclude_none=True)
        )

    return {
        "version": 1,
        "kind": "workflow",
        "workflow": RepoWorkflowDocument.model_validate(
            {
                "name": getattr(recipe, "name", ""),
                "description": getattr(recipe, "description", None),
                "enabled": bool(getattr(recipe, "enabled", True)),
                "clear_timeout_sec": getattr(recipe, "clear_timeout_sec", None),
                "communications": communications,
                "recipe_ingredients": steps,
            }
        ).model_dump(exclude_none=True),
    }


def _iter_action_payloads(document: Any) -> list[dict[str, Any]]:
    if not document:
        return []
    if isinstance(document, list):
        return [item for item in document if _looks_like_action_payload(item)]
    if not isinstance(document, dict):
        raise RepoSyncError("Action document must be an object or list")
    if _document_declares_kind(document, "action"):
        return []
    if isinstance(document.get("action"), dict):
        return [document["action"]] if _looks_like_action_payload(document["action"]) else []
    if isinstance(document.get("actions"), list):
        return [item for item in document["actions"] if _looks_like_action_payload(item)]
    return [document] if _looks_like_action_payload(document) else []


def _iter_workflow_payloads(document: Any) -> list[dict[str, Any]]:
    if not document:
        return []
    if isinstance(document, list):
        return [item for item in document if _looks_like_workflow_payload(item)]
    if not isinstance(document, dict):
        raise RepoSyncError("Workflow document must be an object or list")
    if _document_declares_kind(document, "workflow"):
        return []
    if isinstance(document.get("workflow"), dict):
        return [document["workflow"]] if _looks_like_workflow_payload(document["workflow"]) else []
    if isinstance(document.get("workflows"), list):
        return [item for item in document["workflows"] if _looks_like_workflow_payload(item)]
    return [document] if _looks_like_workflow_payload(document) else []


def _iter_rule_groups(document: Any) -> list[dict[str, Any]]:
    if not document:
        return []
    if isinstance(document, list):
        return [item for item in document if isinstance(item, dict)]
    if not isinstance(document, dict):
        raise RepoSyncError("Alert rule document must be an object or list")
    if isinstance(document.get("groups"), list):
        return [item for item in document["groups"] if isinstance(item, dict)]
    if isinstance(document.get("rules"), list):
        return [document]
    return []


def _document_declares_kind(document: dict[str, Any], expected_family: str) -> bool:
    kind = str(document.get("kind") or "").strip().lower()
    if not kind:
        if expected_family == "action":
            return "workflow" in document or "workflows" in document
        return "action" in document or "actions" in document
    if expected_family == "action":
        return kind.startswith("workflow")
    return kind.startswith("action")


def _looks_like_action_payload(document: Any) -> bool:
    if not isinstance(document, dict):
        return False
    if "recipe_ingredients" in document:
        return False
    return bool(str(document.get("task_key_template") or "").strip()) and bool(
        str(document.get("execution_target") or "").strip()
    )


def _looks_like_workflow_payload(document: Any) -> bool:
    if not isinstance(document, dict):
        return False
    recipe_ingredients = document.get("recipe_ingredients")
    return bool(str(document.get("name") or "").strip()) and isinstance(
        recipe_ingredients,
        list,
    )


class RepoSyncService:
    """Handles Git-backed import/export flows for UI configuration objects."""

    def __init__(self, db: AsyncSession | None = None) -> None:
        self.db = db
        self.settings = get_settings()
        self.git_manager = get_git_manager()
        self.rule_manager = get_prometheus_rule_manager()
        self.crd_manager = get_prometheus_crd_manager()
        self.prometheus = get_prometheus_client()

    def _require_db(self) -> AsyncSession:
        if self.db is None:
            raise RepoSyncError("Database session is required for this operation")
        return self.db

    async def _ensure_git_repo(self) -> Path:
        if not self.settings.git_enabled:
            raise RepoSyncError("Git integration is not enabled")
        if not self.settings.git_repo_url:
            raise RepoSyncError("Git repository URL is not configured")
        if not await self.git_manager.clone_or_pull():
            raise RepoSyncError("Failed to clone or pull the Git repository")
        assert self.git_manager.repo_path is not None
        return self.git_manager.repo_path

    async def _read_repo_documents(self, relative_dir: str) -> list[tuple[Path, Any]]:
        repo_path = await self._ensure_git_repo()
        normalized_dir = _normalize_repo_directory(relative_dir, label="Git")
        base_dir = repo_path / normalized_dir
        if not base_dir.exists():
            return []

        files = sorted(
            path
            for path in base_dir.rglob("*")
            if path.is_file() and path.suffix.lower() in REPO_FILE_SUFFIXES
        )
        return [(path, _load_repo_document(path)) for path in files]

    async def _build_export_changes(
        self,
        *,
        relative_dir: str,
        new_files: dict[str, str],
    ) -> dict[str, str | None]:
        repo_path = await self._ensure_git_repo()
        normalized_dir = _normalize_repo_directory(relative_dir, label="Git")
        base_dir = repo_path / normalized_dir
        changes: dict[str, str | None] = dict(new_files)

        if base_dir.exists():
            for path in base_dir.rglob("*"):
                if not path.is_file() or path.suffix.lower() not in REPO_FILE_SUFFIXES:
                    continue
                rel_path = path.relative_to(repo_path).as_posix()
                if rel_path not in new_files:
                    changes[rel_path] = None
        return changes

    async def _finalize_git_export(
        self,
        *,
        changes: dict[str, str | None],
        commit_message: str,
        pr_title: str,
        pr_description: str,
        success_message: str,
        no_change_message: str,
        extra: dict[str, Any],
    ) -> dict[str, Any]:
        success, branch_name = await self.git_manager.commit_and_push_files(
            changes,
            commit_message,
            branch_prefix="poundcake-sync",
        )
        if not success:
            raise RepoSyncError("Failed to commit and push Git changes")

        result: dict[str, Any] = {
            "status": "success",
            "message": no_change_message if not branch_name else success_message,
            **extra,
        }
        if not branch_name:
            return result

        result["branch"] = branch_name
        pr_result = await self.git_manager.create_pull_request(
            branch_name,
            pr_title,
            pr_description,
        )
        if pr_result:
            result["pull_request"] = {
                "number": pr_result.get("number") or pr_result.get("iid"),
                "url": pr_result.get("html_url") or pr_result.get("web_url"),
            }
        return result

    async def _load_actions(self) -> list[Ingredient]:
        db = self._require_db()
        result = await db.execute(
            select(Ingredient).where(
                not_(Ingredient.task_key_template.like(f"{MANAGED_TASK_PREFIX}%"))
            )
        )
        return result.scalars().all()

    async def _load_workflows(self) -> list[Recipe]:
        db = self._require_db()
        result = await db.execute(
            select(Recipe).options(
                joinedload(Recipe.recipe_ingredients).joinedload(RecipeIngredient.ingredient)
            )
        )
        return [
            recipe
            for recipe in result.unique().scalars().all()
            if not is_hidden_workflow_recipe(recipe)
        ]

    async def export_workflow_actions(self) -> dict[str, Any]:
        actions = await self._load_actions()
        workflows = await self._load_workflows()

        actions_dir = _normalize_repo_directory(
            self.settings.git_actions_path,
            label="Actions",
        )
        workflows_dir = _normalize_repo_directory(
            self.settings.git_workflows_path,
            label="Workflows",
        )

        action_files = {
            f"{actions_dir}/{_action_file_name(action)}": _yaml_text(_action_export_payload(action))
            for action in actions
        }
        workflow_files = {
            f"{workflows_dir}/{_workflow_file_name(workflow)}": _yaml_text(
                _workflow_export_payload(workflow)
            )
            for workflow in workflows
        }
        overlap = sorted(set(action_files).intersection(workflow_files))
        if overlap:
            raise RepoSyncError(
                "Workflow and action export file names collide: " + ", ".join(overlap)
            )

        if actions_dir == workflows_dir:
            changes = await self._build_export_changes(
                relative_dir=actions_dir,
                new_files={**action_files, **workflow_files},
            )
        else:
            changes = await self._build_export_changes(
                relative_dir=actions_dir,
                new_files=action_files,
            )
            changes.update(
                await self._build_export_changes(
                    relative_dir=workflows_dir,
                    new_files=workflow_files,
                )
            )

        return await self._finalize_git_export(
            changes=changes,
            commit_message=(
                "Export PoundCake workflows and actions\n\n"
                f"Workflows: {len(workflows)}\n"
                f"Actions: {len(actions)}"
            ),
            pr_title="Export PoundCake workflows and actions",
            pr_description=(
                "## PoundCake configuration export\n\n"
                f"- Workflows: `{len(workflows)}`\n"
                f"- Actions: `{len(actions)}`\n"
                f"- Workflow directory: `{workflows_dir}`\n"
                f"- Action directory: `{actions_dir}`"
            ),
            success_message="Exported workflows and actions to Git.",
            no_change_message="Workflows and actions are already in sync with Git.",
            extra={
                "exported": {
                    "workflows": len(workflows),
                    "actions": len(actions),
                    "workflows_path": workflows_dir,
                    "actions_path": actions_dir,
                }
            },
        )

    async def import_workflow_actions(self) -> dict[str, Any]:
        db = self._require_db()
        actions_dir = _normalize_repo_directory(self.settings.git_actions_path, label="Actions")
        workflows_dir = _normalize_repo_directory(
            self.settings.git_workflows_path,
            label="Workflows",
        )
        if actions_dir == workflows_dir:
            shared_docs = await self._read_repo_documents(actions_dir)
            action_docs = shared_docs
            workflow_docs = shared_docs
        else:
            action_docs = await self._read_repo_documents(actions_dir)
            workflow_docs = await self._read_repo_documents(workflows_dir)

        existing_actions = await self._load_actions()
        actions_by_identity = {
            _action_identity_from_record(action): action for action in existing_actions
        }
        actions_by_task_key: dict[str, list[Any]] = {}
        for action in existing_actions:
            actions_by_task_key.setdefault(str(action.task_key_template), []).append(action)

        action_created = 0
        action_updated = 0

        for _, document in action_docs:
            for raw_payload in _iter_action_payloads(document):
                payload = IngredientCreate.model_validate(raw_payload).model_dump(exclude_none=True)
                identity = _action_identity_from_payload(payload)
                existing = actions_by_identity.get(identity)
                if existing is None:
                    same_name = actions_by_task_key.get(str(payload["task_key_template"]), [])
                    if len(same_name) == 1:
                        existing = same_name[0]

                if existing is None:
                    created = await create_ingredient(
                        _fake_request(),
                        IngredientCreate.model_validate(payload),
                        db,
                    )
                    action_created += 1
                    record = created
                else:
                    record = await update_ingredient(
                        int(existing.id),
                        IngredientUpdate.model_validate(payload),
                        db,
                    )
                    action_updated += 1

                actions_by_identity[_action_identity_from_record(record)] = record
                actions_by_task_key.setdefault(str(record.task_key_template), [])
                actions_by_task_key[str(record.task_key_template)] = [record]

        workflow_created = 0
        workflow_updated = 0
        existing_workflows = {workflow.name: workflow for workflow in await self._load_workflows()}

        for _, document in workflow_docs:
            for raw_payload in _iter_workflow_payloads(document):
                workflow_payload = RepoWorkflowDocument.model_validate(raw_payload).model_dump(
                    exclude_none=True
                )
                resolved_steps: list[dict[str, Any]] = []
                for raw_step in workflow_payload["recipe_ingredients"]:
                    step = RepoWorkflowStep.model_validate(raw_step)
                    action_ref = step.action.model_dump()
                    action = actions_by_identity.get(_action_identity_from_payload(action_ref))
                    if action is None:
                        same_name = actions_by_task_key.get(
                            str(action_ref["task_key_template"]), []
                        )
                        if len(same_name) == 1:
                            action = same_name[0]
                    if action is None:
                        raise RepoSyncError(
                            "Workflow import could not resolve action "
                            f"'{action_ref['task_key_template']}'"
                        )
                    resolved_steps.append(
                        {
                            "ingredient_id": int(action.id),
                            "step_order": step.step_order,
                            "on_success": step.on_success,
                            "parallel_group": step.parallel_group,
                            "depth": step.depth,
                            "execution_payload_override": step.execution_payload_override,
                            "execution_parameters_override": step.execution_parameters_override,
                            "expected_duration_sec_override": step.expected_duration_sec_override,
                            "timeout_duration_sec_override": step.timeout_duration_sec_override,
                            "run_phase": step.run_phase,
                            "run_condition": step.run_condition,
                        }
                    )

                payload = {
                    "name": workflow_payload["name"],
                    "description": workflow_payload.get("description"),
                    "enabled": workflow_payload.get("enabled", True),
                    "clear_timeout_sec": workflow_payload.get("clear_timeout_sec"),
                    "communications": workflow_payload.get(
                        "communications", {"mode": "inherit", "routes": []}
                    ),
                    "recipe_ingredients": resolved_steps,
                }
                existing = existing_workflows.get(str(payload["name"]))
                if existing is None:
                    await create_recipe(
                        _fake_request(),
                        RecipeCreate.model_validate(payload),
                        db,
                    )
                    workflow_created += 1
                else:
                    await update_recipe(
                        int(existing.id),
                        RecipeUpdate.model_validate(payload),
                        db,
                    )
                    workflow_updated += 1

        logger.info(
            "Imported workflows and actions from Git",
            extra={
                "req_id": REPO_SYNC_REQ_ID,
                "workflows_created": workflow_created,
                "workflows_updated": workflow_updated,
                "actions_created": action_created,
                "actions_updated": action_updated,
            },
        )
        return {
            "status": "success",
            "message": "Imported workflows and actions from Git.",
            "imported": {
                "workflows_created": workflow_created,
                "workflows_updated": workflow_updated,
                "actions_created": action_created,
                "actions_updated": action_updated,
            },
        }

    async def clear_workflow_actions(self) -> dict[str, Any]:
        recipes = await self._load_workflows()
        actions = await self._load_actions()
        db = self._require_db()

        for recipe in recipes:
            await delete_recipe(_fake_request(), int(recipe.id), db)
        for action in actions:
            await delete_ingredient(_fake_request(), int(action.id), db)

        return {
            "status": "success",
            "message": "Cleared workflows and actions from PoundCake.",
            "cleared": {
                "workflows": len(recipes),
                "actions": len(actions),
            },
        }

    async def _current_alert_rules(self) -> list[dict[str, Any]]:
        if self.settings.prometheus_use_crds:
            rules: list[dict[str, Any]] = []
            for crd in await self.crd_manager.get_prometheus_rules():
                crd_name = crd.get("metadata", {}).get("name", "")
                for group in crd.get("spec", {}).get("groups", []) or []:
                    group_name = group.get("name", "")
                    for rule in group.get("rules", []) or []:
                        if not rule.get("alert"):
                            continue
                        rules.append(
                            {
                                "group": group_name,
                                "file": crd_name,
                                "rule": normalize_rule_data(str(rule.get("alert") or ""), rule),
                            }
                        )
            return rules

        live_rules = await self.prometheus.get_rules()
        return [
            {
                "group": str(rule.get("group") or ""),
                "file": str(rule.get("file") or rule.get("name") or ""),
                "rule": normalize_rule_data(
                    str(rule.get("name") or ""),
                    {
                        "alert": rule.get("name"),
                        "expr": rule.get("query"),
                        "for": rule.get("duration"),
                        "labels": rule.get("labels"),
                        "annotations": rule.get("annotations"),
                    },
                ),
            }
            for rule in live_rules
            if rule.get("name")
        ]

    async def export_alert_rules(self) -> dict[str, Any]:
        rules = await self._current_alert_rules()
        rules_dir = _normalize_repo_directory(self.settings.git_rules_path, label="Alert rules")
        files: dict[str, str] = {}

        if self.settings.git_file_per_alert:
            for item in rules:
                rule_name = str(item["rule"].get("alert") or item["rule"].get("record") or "rule")
                group_name = str(item["group"] or "default")
                file_hint = sanitize_crd_name(str(item["file"] or rule_name))
                file_name = self.rule_manager._get_file_path(rule_name, group_name, file_hint)
                files[f"{rules_dir}/{file_name}"] = _yaml_text(
                    {
                        "groups": [
                            {
                                "name": group_name,
                                "rules": [item["rule"]],
                            }
                        ]
                    }
                )
        else:
            grouped: dict[str, dict[str, Any]] = {}
            for item in rules:
                group_name = str(item["group"] or "default")
                file_hint = sanitize_crd_name(str(item["file"] or group_name))
                file_name = self.rule_manager._get_file_path(
                    str(item["rule"].get("alert") or item["rule"].get("record") or group_name),
                    group_name,
                    file_hint,
                )
                document = grouped.setdefault(file_name, {"groups": []})
                groups = document.setdefault("groups", [])
                group = next((entry for entry in groups if entry.get("name") == group_name), None)
                if group is None:
                    group = {"name": group_name, "rules": []}
                    groups.append(group)
                group["rules"].append(item["rule"])
            files = {
                f"{rules_dir}/{name}": _yaml_text(payload) for name, payload in grouped.items()
            }

        changes = await self._build_export_changes(relative_dir=rules_dir, new_files=files)
        return await self._finalize_git_export(
            changes=changes,
            commit_message=f"Export PoundCake alert rules\n\nAlert rules: {len(rules)}",
            pr_title="Export PoundCake alert rules",
            pr_description=(
                "## PoundCake alert-rule export\n\n"
                f"- Alert rules: `{len(rules)}`\n"
                f"- Rule directory: `{rules_dir}`"
            ),
            success_message="Exported alert rules to Git.",
            no_change_message="Alert rules are already in sync with Git.",
            extra={
                "exported": {
                    "alert_rules": len(rules),
                    "rules_path": rules_dir,
                }
            },
        )

    async def import_alert_rules(self) -> dict[str, Any]:
        if not self.settings.prometheus_use_crds:
            raise RepoSyncError("Alert-rule import requires prometheus.useCrds=true")

        imported = 0
        for path, document in await self._read_repo_documents(self.settings.git_rules_path):
            relative_name = path.name
            for group in _iter_rule_groups(document):
                group_name = str(group.get("name") or "").strip()
                if not group_name:
                    raise RepoSyncError(f"Alert rule file '{path.name}' is missing a group name")
                for raw_rule in group.get("rules", []) or []:
                    if not isinstance(raw_rule, dict):
                        continue
                    rule_name = str(raw_rule.get("alert") or raw_rule.get("record") or "").strip()
                    if not rule_name:
                        continue
                    result = await self.crd_manager.create_or_update_rule(
                        rule_name,
                        group_name,
                        sanitize_crd_name(relative_name),
                        normalize_rule_data(rule_name, raw_rule),
                    )
                    if result.get("status") == "error":
                        raise RepoSyncError(
                            str(result.get("message") or "Alert-rule import failed")
                        )
                    imported += 1

        return {
            "status": "success",
            "message": "Imported alert rules from Git.",
            "imported": {
                "alert_rules": imported,
            },
        }

    async def clear_alert_rules(self) -> dict[str, Any]:
        if not self.settings.prometheus_use_crds:
            raise RepoSyncError("Alert-rule clear requires prometheus.useCrds=true")

        rules = await self._current_alert_rules()
        cleared = 0
        for item in rules:
            rule = item["rule"]
            rule_name = str(rule.get("alert") or rule.get("record") or "").strip()
            if not rule_name:
                continue
            result = await self.crd_manager.delete_rule(
                rule_name,
                str(item["group"] or ""),
                str(item["file"] or rule_name),
            )
            if result.get("status") == "error":
                raise RepoSyncError(str(result.get("message") or "Alert-rule clear failed"))
            cleared += 1

        return {
            "status": "success",
            "message": "Cleared alert rules from PoundCake.",
            "cleared": {
                "alert_rules": cleared,
            },
        }
