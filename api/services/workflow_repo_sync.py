"""Git-backed import/export for user-facing recipes via the GitHub helper."""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any

import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from api.core.config import get_settings
from api.core.time import utc_now_db
from api.models.models import Ingredient, Recipe, RecipeIngredient
from api.plugins.github.client import GitHubClient, GitHubClientError
from api.schemas.schemas import (
    RecipeCommunicationsConfig,
    RecipeCreate,
    RecipeIngredientCreate,
    RepoSyncPullRequestResponse,
    RepoSyncResponse,
)
from api.services.communications_policy import (
    get_recipe_local_routes,
    get_visible_recipe_steps,
    is_hidden_workflow_recipe,
    route_payloads_for_response,
)
from api.services.credential_manager import read_adapter_credential_with_policy
from api.services.workflow_repo_documents import (
    RepoActionReference,
    RepoWorkflowDocument,
    RepoWorkflowStep,
    dump_workflow_document,
    load_workflow_document,
    workflow_filename,
)


class WorkflowRepoSyncError(RuntimeError):
    """Raised when workflow Git sync cannot complete."""


_SYSTEM_WORKFLOW_PREFIXES = (
    "operator-action:",
    "plugin-health-check:",
    "plugin-content-sync:",
    "plugin-",
    "alertmanager-sync-",
)


def is_system_workflow_recipe(recipe: Recipe) -> bool:
    name = str(getattr(recipe, "name", "") or "")
    return name.startswith(_SYSTEM_WORKFLOW_PREFIXES)


def _normalize_repo_directory(value: str, *, label: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        raise WorkflowRepoSyncError(f"{label} directory is not configured")
    path = PurePosixPath(raw)
    if path.is_absolute() or ".." in path.parts:
        raise WorkflowRepoSyncError(f"{label} directory must be a relative repo path")
    normalized = str(path).strip("/")
    if not normalized or normalized == ".":
        raise WorkflowRepoSyncError(f"{label} directory must not be empty")
    return normalized


def _recipe_to_document(recipe: Recipe) -> RepoWorkflowDocument:
    local_routes = get_recipe_local_routes(recipe)
    communications = (
        route_payloads_for_response(
            mode="local",
            effective_source="local",
            routes=local_routes,
        )
        if local_routes
        else {"mode": "inherit", "routes": []}
    )
    steps: list[RepoWorkflowStep] = []
    for step in get_visible_recipe_steps(recipe):
        ingredient = step.ingredient
        if ingredient is None:
            raise WorkflowRepoSyncError(
                f"recipe {recipe.name!r} step {step.step_order} is missing its ingredient"
            )
        steps.append(
            RepoWorkflowStep(
                step_order=step.step_order,
                on_success=step.on_success,
                parallel_group=step.parallel_group,
                depth=step.depth,
                run_phase=step.run_phase,
                run_condition=step.run_condition,
                service_payload=(
                    step.service_payload if isinstance(step.service_payload, dict) else None
                ),
                service_exec_parameters_override=(
                    step.service_exec_parameters_override
                    if isinstance(step.service_exec_parameters_override, dict)
                    else None
                ),
                action=RepoActionReference(
                    service_type=ingredient.service_type,
                    service_exec=ingredient.service_exec,
                    task_key_template=ingredient.task_key_template,
                    destination_target=ingredient.destination_target or "",
                ),
            )
        )
    if not steps:
        raise WorkflowRepoSyncError(f"recipe {recipe.name!r} has no exportable steps")
    return RepoWorkflowDocument(
        name=recipe.name,
        description=recipe.description,
        enabled=recipe.enabled,
        clear_timeout_sec=recipe.clear_timeout_sec,
        communications=communications,
        recipe_ingredients=steps,
    )


def _document_to_create_payload(
    document: RepoWorkflowDocument,
    *,
    ingredients: list[Any],
) -> RecipeCreate:
    catalog: dict[tuple[str, str, str], Ingredient] = {}
    for ingredient in ingredients:
        if not ingredient.is_active:
            continue
        catalog[
            (
                str(ingredient.service_type),
                str(ingredient.service_exec),
                str(ingredient.task_key_template),
            )
        ] = ingredient
    missing: list[str] = []
    steps: list[RecipeIngredientCreate] = []
    for step in document.recipe_ingredients:
        key = (step.action.service_type, step.action.service_exec, step.action.task_key_template)
        ingredient = catalog.get(key)
        if ingredient is None:
            missing.append(
                f"{step.action.service_type}/{step.action.service_exec}/{step.action.task_key_template}"
            )
            continue
        steps.append(
            RecipeIngredientCreate(
                ingredient_id=ingredient.id,
                step_order=step.step_order,
                on_success=step.on_success,  # type: ignore[arg-type]
                parallel_group=step.parallel_group,
                depth=step.depth,
                run_phase=step.run_phase,  # type: ignore[arg-type]
                run_condition=step.run_condition,  # type: ignore[arg-type]
                service_payload=step.service_payload,
                service_exec_parameters_override=step.service_exec_parameters_override,
            )
        )
    if missing:
        raise WorkflowRepoSyncError(
            "import requires registered ingredient templates: " + ", ".join(missing)
        )
    communications = RecipeCommunicationsConfig.model_validate(document.communications)
    return RecipeCreate(
        name=document.name,
        description=document.description,
        enabled=document.enabled,
        clear_timeout_sec=document.clear_timeout_sec,
        recipe_ingredients=steps,
        communications=communications,
    )


def collect_workflow_export_files(
    recipes: list[Recipe],
    *,
    directory: str,
) -> tuple[dict[str, str], list[str]]:
    """Serialize exportable recipes; skip recipes that have no usable steps."""
    files: dict[str, str] = {}
    skipped: list[str] = []
    for recipe in recipes:
        try:
            document = _recipe_to_document(recipe)
        except (WorkflowRepoSyncError, ValueError) as exc:
            skipped.append(f"{recipe.name}: {exc}")
            continue
        files[f"{directory}/{workflow_filename(recipe.name)}"] = dump_workflow_document(document)
    return files, skipped


async def _github_client() -> GitHubClient:
    client = GitHubClient()
    credential = await read_adapter_credential_with_policy(
        service_type="github",
        credential_type="github_token",
        credential_key_id="default",
    )
    if credential is not None:
        client = client.with_credentials(credential.payload)
        client.allow_public_read = bool(credential.allow_public_read)
    if not str(client.default_repo or "").strip():
        raise WorkflowRepoSyncError("GitHub repository is not configured")
    return client


async def export_workflows(db: AsyncSession) -> RepoSyncResponse:
    settings = get_settings()
    directory = _normalize_repo_directory(settings.git_workflows_path, label="workflows")
    result = await db.execute(
        select(Recipe).options(
            joinedload(Recipe.recipe_ingredients).joinedload(RecipeIngredient.ingredient)
        )
    )
    recipes = [
        row
        for row in result.unique().scalars().all()
        if not is_hidden_workflow_recipe(row) and not is_system_workflow_recipe(row)
    ]
    files, skipped = collect_workflow_export_files(recipes, directory=directory)
    if not files:
        raise WorkflowRepoSyncError("no user-facing workflows to export")
    client = await _github_client()
    stamp = utc_now_db().strftime("%Y%m%d%H%M%S")
    branch = f"poundcake-workflows-{stamp}"
    try:
        pr = await client.commit_and_pr(
            branch=branch,
            files=files,
            commit_message="Export PoundCake workflows",
            title="Export PoundCake workflows",
            body="This pull request was created by PoundCake workflow export. Review before merging.",
        )
    except GitHubClientError as exc:
        raise WorkflowRepoSyncError(str(exc)) from exc
    pull_request = pr.get("pull_request") if isinstance(pr, dict) else None
    pr_payload = None
    if isinstance(pull_request, dict):
        pr_payload = RepoSyncPullRequestResponse(
            number=pull_request.get("number"),
            url=pull_request.get("url") or pull_request.get("html_url"),
        )
    message = f"Exported {len(files)} workflow file(s)."
    if skipped:
        message += f" Skipped {len(skipped)} workflow(s) without exportable steps."
    return RepoSyncResponse(
        status="exported",
        message=message,
        branch=branch,
        pull_request=pr_payload,
        exported={"files": len(files), "workflows": len(files)},
        skipped={"workflows": len(skipped)},
        warnings=skipped or None,
    )


async def import_workflows(db: AsyncSession) -> tuple[RepoSyncResponse, list[RecipeCreate]]:
    settings = get_settings()
    directory = _normalize_repo_directory(settings.git_workflows_path, label="workflows")
    client = await _github_client()
    try:
        listing = await client.list_files(path=directory, recursive=True)
    except GitHubClientError as exc:
        raise WorkflowRepoSyncError(str(exc)) from exc
    files = listing.get("files") if isinstance(listing, dict) else None
    if not isinstance(files, list):
        raise WorkflowRepoSyncError("GitHub list_files did not return a file list")
    documents: list[RepoWorkflowDocument] = []
    warnings: list[str] = []
    for item in files:
        path = str(
            item if isinstance(item, str) else item.get("path") if isinstance(item, dict) else ""
        )
        if not path.endswith((".yaml", ".yml")):
            continue
        try:
            raw = await client.read_file(path=path)
        except GitHubClientError as exc:
            warnings.append(f"{path}: {exc}")
            continue
        content = raw.get("content") if isinstance(raw, dict) else None
        if not isinstance(content, str):
            warnings.append(f"{path}: missing content")
            continue
        try:
            documents.append(load_workflow_document(yaml.safe_load(content)))
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"{path}: {exc}")
    ingredients_result = await db.execute(select(Ingredient))
    ingredients = list(ingredients_result.scalars().all())
    payloads = [
        _document_to_create_payload(document, ingredients=ingredients) for document in documents
    ]
    return (
        RepoSyncResponse(
            status="imported",
            message=f"Parsed {len(payloads)} workflow file(s).",
            imported={"workflows": len(payloads)},
            skipped={"files": max(0, len(files) - len(payloads))},
            warnings=warnings or None,
        ),
        payloads,
    )
