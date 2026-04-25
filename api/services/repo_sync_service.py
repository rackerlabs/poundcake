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
from api.services.alert_rule_repo import (
    ALERT_RULE_SOURCE_FORMAT_ADDITIONAL_MAP,
    AlertRuleSource,
    build_alert_rule_repo_index,
    default_wrapper_key_for_path,
    delete_rule_from_document,
    document_has_rules,
    dump_alert_rule_document,
    dump_round_trip_alert_rule_document,
    iter_rule_groups as iter_alert_rule_groups,
    load_round_trip_repo_documents,
    load_alert_rule_sources_from_annotations,
    looks_like_repo_relative_rule_path,
    normalize_repo_relative_path,
    render_alert_rule_document,
    upsert_rule_in_document,
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


def _normalize_promql_expr_for_compare(value: str) -> str:
    """Normalize PromQL whitespace outside quoted strings for semantic comparisons."""
    result: list[str] = []
    quote: str | None = None
    escaped = False
    pending_space = False
    idx = 0

    while idx < len(value):
        char = value[idx]

        if quote is None and char == "#":
            while idx < len(value) and value[idx] not in "\r\n":
                idx += 1
            pending_space = True
            continue

        if quote is None and char.isspace():
            pending_space = True
            idx += 1
            continue

        if quote is None and char in {'"', "'", "`"}:
            if pending_space and result:
                result.append(" ")
            pending_space = False
            quote = char
            escaped = False
            result.append(char)
            idx += 1
            continue

        if quote is not None:
            result.append(char)
            if quote != "`" and char == "\\" and not escaped:
                escaped = True
            elif char == quote and not escaped:
                quote = None
                escaped = False
            else:
                escaped = False
            idx += 1
            continue

        if pending_space and result:
            result.append(" ")
        pending_space = False
        result.append(char)
        idx += 1

    return "".join(result).strip()


def _normalize_rule_data_for_compare(rule_name: str, rule_data: dict[str, Any]) -> dict[str, Any]:
    """Normalize alert rule data for semantic export comparisons."""
    normalized = normalize_rule_data(rule_name, rule_data)
    expr = normalized.get("expr")
    if isinstance(expr, str):
        normalized["expr"] = _normalize_promql_expr_for_compare(expr)
    return normalized


def _is_skippable_invalid_alert_rule_result(result: dict[str, Any]) -> bool:
    """Return True when a CRD write failure is an invalid-rule validation error."""
    code = result.get("code")
    if isinstance(code, int) and code == 422:
        return True

    reason = str(result.get("reason") or result.get("body_reason") or "").strip().lower()
    if reason == "invalid":
        return True

    message = " ".join(
        str(part or "").strip()
        for part in (
            result.get("message"),
            result.get("body_message"),
        )
    ).lower()
    return (
        "prometheusrulevalidate.monitoring.coreos.com" in message
        or "rules are not valid" in message
    )


def _format_invalid_alert_rule_summary(
    *,
    rule_name: str,
    relative_path: str,
    result: dict[str, Any],
) -> str:
    """Build a short user-facing summary for a skipped invalid rule."""
    raw_reason = str(
        result.get("body_message")
        or result.get("message")
        or result.get("reason")
        or "PrometheusRule validation failed"
    ).strip()
    compact_reason = re.sub(r"\s+", " ", raw_reason)
    if len(compact_reason) > 220:
        compact_reason = f"{compact_reason[:217].rstrip()}..."
    return f"{rule_name} in {relative_path}: {compact_reason}"


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


def _format_action_reference(payload: dict[str, Any]) -> str:
    task_key = str(payload.get("task_key_template") or "").strip() or "unknown"
    execution_target = str(payload.get("execution_target") or "").strip() or "unknown-target"
    execution_engine = str(payload.get("execution_engine") or "").strip() or "unknown-engine"
    destination_target = str(payload.get("destination_target") or "").strip()
    if destination_target:
        return f"{task_key} ({execution_engine}/{execution_target}:{destination_target})"
    return f"{task_key} ({execution_engine}/{execution_target})"


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
    try:
        return [group for group, _source_format, _wrapper_key in iter_alert_rule_groups(document)]
    except ValueError as exc:
        raise RepoSyncError(str(exc)) from exc


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


def _document_entity_flags(document: Any) -> tuple[bool, bool]:
    if isinstance(document, dict):
        has_actions = isinstance(document.get("action"), dict) or isinstance(
            document.get("actions"),
            list,
        )
        has_workflows = isinstance(document.get("workflow"), dict) or isinstance(
            document.get("workflows"),
            list,
        )
        if has_actions or has_workflows:
            return has_actions, has_workflows
    return bool(_iter_action_payloads(document)), bool(_iter_workflow_payloads(document))


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

    async def _build_entity_export_changes(
        self,
        *,
        relative_dir: str,
        new_files: dict[str, str],
        entity_family: str,
    ) -> dict[str, str | None]:
        repo_path = await self._ensure_git_repo()
        normalized_dir = _normalize_repo_directory(relative_dir, label="Git")
        base_dir = repo_path / normalized_dir
        changes: dict[str, str | None] = dict(new_files)

        if not base_dir.exists():
            return changes

        for path in base_dir.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in REPO_FILE_SUFFIXES:
                continue
            rel_path = path.relative_to(repo_path).as_posix()
            document = _load_repo_document(path)
            has_actions, has_workflows = _document_entity_flags(document)
            if has_actions and has_workflows:
                raise RepoSyncError(
                    "Split export cannot manage mixed action/workflow file "
                    f"'{path.relative_to(base_dir).as_posix()}'."
                )

            if entity_family == "action" and has_actions and rel_path not in new_files:
                changes[rel_path] = None
            if entity_family == "workflow" and has_workflows and rel_path not in new_files:
                changes[rel_path] = None

        return changes

    def _build_action_catalog(
        self,
        actions: list[Any],
    ) -> tuple[dict[tuple[str, str, str, str], Any], dict[str, list[Any]]]:
        actions_by_identity = {_action_identity_from_record(action): action for action in actions}
        actions_by_task_key: dict[str, list[Any]] = {}
        for action in actions:
            actions_by_task_key.setdefault(str(action.task_key_template), []).append(action)
        return actions_by_identity, actions_by_task_key

    async def _import_actions_from_documents(
        self,
        action_docs: list[tuple[Path, Any]],
    ) -> tuple[dict[str, int], dict[tuple[str, str, str, str], Any], dict[str, list[Any]]]:
        db = self._require_db()
        existing_actions = await self._load_actions()
        actions_by_identity, actions_by_task_key = self._build_action_catalog(existing_actions)

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
                actions_by_task_key[str(record.task_key_template)] = [record]

        return (
            {
                "actions_created": action_created,
                "actions_updated": action_updated,
            },
            actions_by_identity,
            actions_by_task_key,
        )

    async def _import_workflows_from_documents(
        self,
        workflow_docs: list[tuple[Path, Any]],
        *,
        actions_by_identity: dict[tuple[str, str, str, str], Any] | None = None,
        actions_by_task_key: dict[str, list[Any]] | None = None,
    ) -> dict[str, Any]:
        db = self._require_db()
        if actions_by_identity is None or actions_by_task_key is None:
            current_actions = await self._load_actions()
            actions_by_identity, actions_by_task_key = self._build_action_catalog(current_actions)

        workflow_created = 0
        workflow_updated = 0
        workflow_skipped = 0
        warnings: list[str] = []
        existing_workflows = {workflow.name: workflow for workflow in await self._load_workflows()}

        for path, document in workflow_docs:
            for raw_payload in _iter_workflow_payloads(document):
                workflow_payload = RepoWorkflowDocument.model_validate(raw_payload).model_dump(
                    exclude_none=True
                )
                resolved_steps: list[dict[str, Any]] = []
                missing_refs: list[str] = []

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
                        missing_refs.append(_format_action_reference(action_ref))
                        continue

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

                if missing_refs:
                    workflow_skipped += 1
                    warnings.append(
                        f"Skipped workflow '{workflow_payload['name']}' from "
                        f"{path.name}: missing actions {', '.join(sorted(set(missing_refs)))}."
                    )
                    continue

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
                    created = await create_recipe(
                        _fake_request(),
                        RecipeCreate.model_validate(payload),
                        db,
                    )
                    workflow_created += 1
                    existing_workflows[str(created.name)] = created
                else:
                    updated = await update_recipe(
                        int(existing.id),
                        RecipeUpdate.model_validate(payload),
                        db,
                    )
                    workflow_updated += 1
                    existing_workflows[str(updated.name)] = updated

        return {
            "imported": {
                "workflows_created": workflow_created,
                "workflows_updated": workflow_updated,
            },
            "skipped": {"workflows": workflow_skipped},
            "warnings": warnings,
        }

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
        if not changes:
            return {
                "status": "success",
                "message": no_change_message,
                **extra,
            }

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

    async def export_actions(self) -> dict[str, Any]:
        actions = await self._load_actions()
        actions_dir = _normalize_repo_directory(
            self.settings.git_actions_path,
            label="Actions",
        )
        action_files = {
            f"{actions_dir}/{_action_file_name(action)}": _yaml_text(_action_export_payload(action))
            for action in actions
        }
        changes = await self._build_entity_export_changes(
            relative_dir=actions_dir,
            new_files=action_files,
            entity_family="action",
        )

        return await self._finalize_git_export(
            changes=changes,
            commit_message=f"Export PoundCake actions\n\nActions: {len(actions)}",
            pr_title="Export PoundCake actions",
            pr_description=(
                "## PoundCake action export\n\n"
                f"- Actions: `{len(actions)}`\n"
                f"- Action directory: `{actions_dir}`"
            ),
            success_message="Exported actions to Git.",
            no_change_message="Actions are already in sync with Git.",
            extra={
                "exported": {
                    "actions": len(actions),
                    "actions_path": actions_dir,
                }
            },
        )

    async def export_workflows(self) -> dict[str, Any]:
        workflows = await self._load_workflows()
        workflows_dir = _normalize_repo_directory(
            self.settings.git_workflows_path,
            label="Workflows",
        )
        workflow_files = {
            f"{workflows_dir}/{_workflow_file_name(workflow)}": _yaml_text(
                _workflow_export_payload(workflow)
            )
            for workflow in workflows
        }
        changes = await self._build_entity_export_changes(
            relative_dir=workflows_dir,
            new_files=workflow_files,
            entity_family="workflow",
        )

        return await self._finalize_git_export(
            changes=changes,
            commit_message=f"Export PoundCake workflows\n\nWorkflows: {len(workflows)}",
            pr_title="Export PoundCake workflows",
            pr_description=(
                "## PoundCake workflow export\n\n"
                f"- Workflows: `{len(workflows)}`\n"
                f"- Workflow directory: `{workflows_dir}`"
            ),
            success_message="Exported workflows to Git.",
            no_change_message="Workflows are already in sync with Git.",
            extra={
                "exported": {
                    "workflows": len(workflows),
                    "workflows_path": workflows_dir,
                }
            },
        )

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

    async def import_actions(self) -> dict[str, Any]:
        actions_dir = _normalize_repo_directory(self.settings.git_actions_path, label="Actions")
        action_docs = await self._read_repo_documents(actions_dir)
        imported, _actions_by_identity, _actions_by_task_key = (
            await self._import_actions_from_documents(action_docs)
        )

        logger.info(
            "Imported actions from Git",
            extra={
                "req_id": REPO_SYNC_REQ_ID,
                **imported,
            },
        )
        total_actions = imported["actions_created"] + imported["actions_updated"]
        return {
            "status": "success",
            "message": (
                f"Imported {total_actions} actions from Git "
                f"({imported['actions_created']} created, {imported['actions_updated']} updated)."
            ),
            "imported": imported,
        }

    async def import_workflows(self) -> dict[str, Any]:
        workflows_dir = _normalize_repo_directory(
            self.settings.git_workflows_path,
            label="Workflows",
        )
        workflow_docs = await self._read_repo_documents(workflows_dir)
        workflow_result = await self._import_workflows_from_documents(workflow_docs)
        imported = workflow_result["imported"]
        skipped = workflow_result["skipped"]
        warnings = workflow_result["warnings"]

        logger.info(
            "Imported workflows from Git",
            extra={
                "req_id": REPO_SYNC_REQ_ID,
                **imported,
                **skipped,
            },
        )
        total_workflows = imported["workflows_created"] + imported["workflows_updated"]
        message = (
            f"Imported {total_workflows} workflows from Git "
            f"({imported['workflows_created']} created, {imported['workflows_updated']} updated)."
        )
        if skipped["workflows"]:
            message += f" Skipped {skipped['workflows']} workflow(s) with missing actions."
        return {
            "status": "success",
            "message": message,
            "imported": imported,
            "skipped": skipped,
            "warnings": warnings,
        }

    async def import_workflow_actions(self) -> dict[str, Any]:
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

        imported_actions, actions_by_identity, actions_by_task_key = (
            await self._import_actions_from_documents(action_docs)
        )
        workflow_result = await self._import_workflows_from_documents(
            workflow_docs,
            actions_by_identity=actions_by_identity,
            actions_by_task_key=actions_by_task_key,
        )
        imported = {**workflow_result["imported"], **imported_actions}
        skipped = workflow_result["skipped"]
        warnings = workflow_result["warnings"]

        logger.info(
            "Imported workflows and actions from Git",
            extra={
                "req_id": REPO_SYNC_REQ_ID,
                **imported,
                **skipped,
            },
        )
        total_workflows = imported["workflows_created"] + imported["workflows_updated"]
        total_actions = imported["actions_created"] + imported["actions_updated"]
        message = f"Imported {total_workflows} workflows and {total_actions} actions from Git."
        if skipped["workflows"]:
            message += f" Skipped {skipped['workflows']} workflow(s) with missing actions."
        return {
            "status": "success",
            "message": message,
            "imported": imported,
            "skipped": skipped,
            "warnings": warnings,
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
                source_map = load_alert_rule_sources_from_annotations(
                    crd.get("metadata", {}).get("annotations")
                )
                for group in crd.get("spec", {}).get("groups", []) or []:
                    group_name = group.get("name", "")
                    for rule in group.get("rules", []) or []:
                        rule_name = str(rule.get("alert") or "").strip()
                        if not rule_name:
                            continue
                        source = source_map.get(rule_name)
                        rules.append(
                            {
                                "group": group_name,
                                "crd": crd_name,
                                "file": source.relative_path if source else None,
                                "source_format": source.source_format if source else None,
                                "wrapper_key": source.wrapper_key if source else None,
                                "rule": normalize_rule_data(rule_name, rule),
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

    def _rule_source_from_item(
        self,
        *,
        item: dict[str, Any],
        rule_name: str,
        group_name: str,
        repo_index: dict[str, Any],
        base_dir: Path | None = None,
    ) -> AlertRuleSource:
        raw_file = str(item.get("file") or "").strip()
        raw_format = str(item.get("source_format") or "").strip()
        raw_wrapper = str(item.get("wrapper_key") or "").strip() or None

        if raw_file and raw_format and looks_like_repo_relative_rule_path(raw_file):
            try:
                source = AlertRuleSource(
                    relative_path=normalize_repo_relative_path(raw_file),
                    source_format=raw_format,
                    wrapper_key=raw_wrapper,
                )
                if base_dir is None or (base_dir / source.relative_path).exists():
                    return source
            except ValueError:
                pass

        repo_entry = repo_index.get(rule_name)
        if repo_entry is not None and str(repo_entry.group_name or "").strip() == group_name:
            return repo_entry.source

        if raw_file and looks_like_repo_relative_rule_path(raw_file):
            try:
                source = AlertRuleSource(relative_path=normalize_repo_relative_path(raw_file))
                if base_dir is None or (base_dir / source.relative_path).exists():
                    return source
            except ValueError:
                pass

        return self._unmapped_rule_source(
            item=item,
            rule_name=rule_name,
            group_name=group_name,
        )

    def _unmapped_rule_source(
        self,
        *,
        item: dict[str, Any],
        rule_name: str,
        group_name: str,
    ) -> AlertRuleSource:
        unmapped_dir = normalize_repo_relative_path(
            str(getattr(self.settings, "git_unmapped_rules_path", "imported") or "imported")
        )
        file_hint = sanitize_crd_name(str(item.get("crd") or rule_name))
        if bool(getattr(self.settings, "git_file_per_alert", True)):
            pattern = str(getattr(self.settings, "git_file_pattern", "{alert_name}.yaml") or "")
            raw_file_name = pattern.format(
                alert_name=rule_name,
                group_name=group_name,
                crd_name=file_hint,
            )
            file_name = PurePosixPath(raw_file_name).name
        else:
            file_name = f"{file_hint}.yaml"
        relative_path = f"{unmapped_dir}/{file_name}"
        return AlertRuleSource(
            relative_path=relative_path,
            source_format=ALERT_RULE_SOURCE_FORMAT_ADDITIONAL_MAP,
            wrapper_key=default_wrapper_key_for_path(relative_path),
        )

    async def _build_alert_rule_export_changes(self) -> dict[str, Any]:
        rules = await self._current_alert_rules()
        repo_path = await self._ensure_git_repo()
        rules_dir = _normalize_repo_directory(self.settings.git_rules_path, label="Alert rules")
        base_dir = repo_path / rules_dir
        try:
            repo_index = build_alert_rule_repo_index(base_dir)
        except ValueError as exc:
            raise RepoSyncError(str(exc)) from exc

        files_by_relative_path: dict[str, list[tuple[str, dict[str, Any], AlertRuleSource]]] = {}
        live_rule_names: set[str] = set()
        for item in rules:
            rule_name = str(
                item["rule"].get("alert") or item["rule"].get("record") or "rule"
            ).strip()
            group_name = str(item["group"] or "default").strip() or "default"
            live_rule_names.add(rule_name)
            source = self._rule_source_from_item(
                item=item,
                rule_name=rule_name,
                group_name=group_name,
                repo_index=repo_index.by_alert_name,
                base_dir=base_dir,
            )
            files_by_relative_path.setdefault(source.relative_path, []).append(
                (group_name, item["rule"], source)
            )

        changes: dict[str, str | None] = {}
        changed_files: list[str] = []
        added_files: list[str] = []
        deleted_files: list[str] = []
        unchanged_files = 0

        for relative_path, records in sorted(files_by_relative_path.items()):
            repo_relative_path = f"{rules_dir}/{relative_path}"
            full_path = base_dir / relative_path

            if not full_path.exists():
                try:
                    document = render_alert_rule_document(records, relative_path=relative_path)
                except ValueError as exc:
                    raise RepoSyncError(str(exc)) from exc
                changes[repo_relative_path] = dump_alert_rule_document(document, relative_path)
                added_files.append(repo_relative_path)
                continue

            try:
                documents = load_round_trip_repo_documents(full_path)
            except Exception as exc:  # noqa: BLE001
                raise RepoSyncError(
                    f"Failed to parse alert rule file '{relative_path}': {exc}"
                ) from exc
            if len(documents) != 1:
                raise RepoSyncError(
                    f"Alert-rule file '{relative_path}' must contain exactly one document for export"
                )

            document = documents[0]
            file_changed = False
            for group_name, live_rule, source in records:
                rule_name = str(live_rule.get("alert") or live_rule.get("record") or "rule").strip()
                repo_entry = repo_index.by_alert_name.get(rule_name)
                repo_rule = repo_entry.rule_data if repo_entry is not None else None
                if (
                    repo_entry is not None
                    and repo_entry.source.relative_path == relative_path
                    and _normalize_rule_data_for_compare(rule_name, repo_rule or {})
                    == _normalize_rule_data_for_compare(rule_name, live_rule)
                ):
                    continue

                document = upsert_rule_in_document(
                    document,
                    source=source,
                    group_name=group_name,
                    rule_name=rule_name,
                    rule_data=live_rule,
                )
                file_changed = True

            for repo_entry in sorted(
                repo_index.by_alert_name.values(),
                key=lambda entry: entry.alert_name,
            ):
                if repo_entry.source.relative_path != relative_path:
                    continue
                if not repo_entry.rule_data.get("alert"):
                    continue
                if repo_entry.alert_name in live_rule_names:
                    continue
                document, deleted = delete_rule_from_document(
                    document,
                    source=repo_entry.source,
                    group_name=repo_entry.group_name,
                    rule_name=repo_entry.alert_name,
                )
                file_changed = file_changed or deleted

            if not file_changed:
                unchanged_files += 1
                continue

            if not document_has_rules(document):
                changes[repo_relative_path] = None
                deleted_files.append(repo_relative_path)
                continue

            updated_text = dump_round_trip_alert_rule_document(document, relative_path)
            if updated_text == full_path.read_text(encoding="utf-8"):
                unchanged_files += 1
                continue
            changes[repo_relative_path] = updated_text
            changed_files.append(repo_relative_path)

        obsolete_entries_by_path: dict[str, list[Any]] = {}
        for repo_entry in sorted(
            repo_index.by_alert_name.values(),
            key=lambda entry: (entry.source.relative_path, entry.alert_name),
        ):
            relative_path = repo_entry.source.relative_path
            if relative_path in files_by_relative_path:
                continue
            if not repo_entry.rule_data.get("alert"):
                continue
            if repo_entry.alert_name in live_rule_names:
                continue
            obsolete_entries_by_path.setdefault(relative_path, []).append(repo_entry)

        for relative_path, obsolete_entries in sorted(obsolete_entries_by_path.items()):
            full_path = base_dir / relative_path
            repo_relative_path = f"{rules_dir}/{relative_path}"
            if not full_path.exists() or repo_relative_path in changes:
                continue

            try:
                documents = load_round_trip_repo_documents(full_path)
            except Exception as exc:  # noqa: BLE001
                raise RepoSyncError(
                    f"Failed to parse alert rule file '{relative_path}': {exc}"
                ) from exc
            if len(documents) != 1:
                raise RepoSyncError(
                    f"Alert-rule file '{relative_path}' must contain exactly one document for export"
                )

            document = documents[0]
            file_changed = False
            for repo_entry in obsolete_entries:
                document, deleted = delete_rule_from_document(
                    document,
                    source=repo_entry.source,
                    group_name=repo_entry.group_name,
                    rule_name=repo_entry.alert_name,
                )
                file_changed = file_changed or deleted

            if not file_changed:
                unchanged_files += 1
                continue
            if not document_has_rules(document):
                changes[repo_relative_path] = None
                deleted_files.append(repo_relative_path)
                continue

            updated_text = dump_round_trip_alert_rule_document(document, relative_path)
            if updated_text == full_path.read_text(encoding="utf-8"):
                unchanged_files += 1
                continue
            changes[repo_relative_path] = updated_text
            changed_files.append(repo_relative_path)

        return {
            "rules": rules,
            "rules_dir": rules_dir,
            "changes": changes,
            "changed_files": sorted(changed_files),
            "added_files": sorted(added_files),
            "deleted_files": sorted(deleted_files),
            "unchanged_files": unchanged_files,
        }

    def _alert_rule_export_details(self, plan: dict[str, Any]) -> dict[str, Any]:
        changes = plan["changes"]
        return {
            "changed_files": plan["changed_files"],
            "added_files": plan["added_files"],
            "deleted_files": plan["deleted_files"],
            "change_count": len(changes),
            "unchanged_files": plan["unchanged_files"],
        }

    async def export_alert_rules_preview(self) -> dict[str, Any]:
        plan = await self._build_alert_rule_export_changes()
        rules = plan["rules"]
        details = self._alert_rule_export_details(plan)
        return {
            "status": "success",
            "message": (
                "Alert-rule export preview has no changes."
                if not plan["changes"]
                else "Alert-rule export preview found changes."
            ),
            "exported": {
                "alert_rules": len(rules),
                "files_changed": len(plan["changed_files"]),
                "files_added": len(plan["added_files"]),
                "files_deleted": len(plan["deleted_files"]),
                "rules_path": plan["rules_dir"],
            },
            "details": details,
        }

    async def export_alert_rules(self) -> dict[str, Any]:
        plan = await self._build_alert_rule_export_changes()
        rules = plan["rules"]
        changes = plan["changes"]
        rules_dir = plan["rules_dir"]
        details = self._alert_rule_export_details(plan)
        if not changes:
            return {
                "status": "success",
                "message": "Alert rules are already in sync with Git.",
                "exported": {
                    "alert_rules": len(rules),
                    "files_written": 0,
                    "files_changed": 0,
                    "files_added": 0,
                    "files_deleted": 0,
                    "rules_path": rules_dir,
                },
                "details": details,
            }

        return await self._finalize_git_export(
            changes=changes,
            commit_message=f"Export PoundCake alert rules\n\nAlert rules: {len(rules)}",
            pr_title="Export PoundCake alert rules",
            pr_description=(
                "## PoundCake alert-rule export\n\n"
                f"- Alert rules: `{len(rules)}`\n"
                f"- Rule directory: `{rules_dir}`\n"
                f"- Changed files: `{len(plan['changed_files'])}`\n"
                f"- Added files: `{len(plan['added_files'])}`\n"
                f"- Deleted files: `{len(plan['deleted_files'])}`"
            ),
            success_message="Exported alert rules to Git.",
            no_change_message="Alert rules are already in sync with Git.",
            extra={
                "exported": {
                    "alert_rules": len(rules),
                    "files_written": len(changes),
                    "files_changed": len(plan["changed_files"]),
                    "files_added": len(plan["added_files"]),
                    "files_deleted": len(plan["deleted_files"]),
                    "rules_path": rules_dir,
                },
                "details": details,
            },
        )

    async def import_alert_rules(self) -> dict[str, Any]:
        if not self.settings.prometheus_use_crds:
            raise RepoSyncError("Alert-rule import requires prometheus.useCrds=true")

        repo_path = await self._ensure_git_repo()
        rules_dir = _normalize_repo_directory(self.settings.git_rules_path, label="Alert rules")
        base_dir = repo_path / rules_dir
        if not base_dir.exists():
            return {
                "status": "success",
                "message": "No alert-rule directory found in Git.",
                "imported": {
                    "alert_rules": 0,
                    "files_scanned": 0,
                    "files_with_groups": 0,
                    "files_skipped": 0,
                },
            }

        files = sorted(
            path
            for path in base_dir.rglob("*")
            if path.is_file() and path.suffix.lower() in REPO_FILE_SUFFIXES
        )
        imported = 0
        files_with_groups = 0
        files_skipped = 0
        invalid_rules = 0
        invalid_rule_files: set[str] = set()
        invalid_rule_examples: list[str] = []

        for path in files:
            relative_path = path.relative_to(base_dir).as_posix()
            try:
                documents = (
                    [
                        document
                        for document in yaml.safe_load_all(path.read_text(encoding="utf-8"))
                        if document is not None
                    ]
                    if path.suffix.lower() != ".json"
                    else [json.loads(path.read_text(encoding="utf-8"))]
                )
            except Exception as exc:  # noqa: BLE001
                raise RepoSyncError(
                    f"Failed to parse alert rule file '{relative_path}': {exc}"
                ) from exc

            grouped_payloads: list[tuple[dict[str, Any], AlertRuleSource]] = []
            for document in documents:
                try:
                    grouped_payloads.extend(
                        (
                            group,
                            AlertRuleSource(
                                relative_path=relative_path,
                                source_format=source_format,
                                wrapper_key=wrapper_key,
                            ),
                        )
                        for group, source_format, wrapper_key in iter_alert_rule_groups(document)
                    )
                except ValueError as exc:
                    raise RepoSyncError(str(exc)) from exc

            if not grouped_payloads:
                files_skipped += 1
                continue

            files_with_groups += 1
            for group, source in grouped_payloads:
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
                        sanitize_crd_name(relative_path),
                        normalize_rule_data(rule_name, raw_rule),
                        source_metadata=source,
                    )
                    if result.get("status") == "error":
                        if _is_skippable_invalid_alert_rule_result(result):
                            invalid_rules += 1
                            invalid_rule_files.add(relative_path)
                            if len(invalid_rule_examples) < 3:
                                invalid_rule_examples.append(
                                    _format_invalid_alert_rule_summary(
                                        rule_name=rule_name,
                                        relative_path=relative_path,
                                        result=result,
                                    )
                                )
                            continue
                        raise RepoSyncError(
                            str(result.get("message") or "Alert-rule import failed")
                        )
                    imported += 1

        if files and imported == 0 and invalid_rules == 0:
            raise RepoSyncError(
                "Scanned alert-rule files in Git but found no importable rules. "
                "Supported formats are groups, rules, spec.groups, and additionalPrometheusRulesMap."
            )

        message_parts = [f"Imported {imported} alert rules from Git."]
        if invalid_rules:
            message_parts.append(
                "Skipped "
                f"{invalid_rules} invalid rule{'s' if invalid_rules != 1 else ''} "
                f"across {len(invalid_rule_files)} file{'s' if len(invalid_rule_files) != 1 else ''}."
            )
            if invalid_rule_examples:
                remaining = invalid_rules - len(invalid_rule_examples)
                examples = "; ".join(invalid_rule_examples)
                if remaining > 0:
                    examples = f"{examples}; and {remaining} more."
                message_parts.append(f"Examples: {examples}")
        if files_skipped:
            message_parts.append(
                f"Skipped {files_skipped} files without supported alert-rule groups."
            )
        message = " ".join(message_parts)

        return {
            "status": "success",
            "message": message,
            "imported": {
                "alert_rules": imported,
                "files_scanned": len(files),
                "files_with_groups": files_with_groups,
                "files_skipped": files_skipped,
                "invalid_rules": invalid_rules,
                "files_with_invalid_rules": len(invalid_rule_files),
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
                str(item.get("crd") or item.get("file") or rule_name),
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
