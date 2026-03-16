"""Workflow commands for the PoundCake CLI."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import click

from cli.client import PoundCakeClient, PoundCakeClientError
from cli.commands.common import (
    compact_update_payload,
    get_client,
    get_output_format,
    read_mapping_file,
)
from cli.utils import parse_json_object, print_error, print_output, render_sections


def _workflow_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "id": item.get("id"),
            "name": item.get("name"),
            "enabled": item.get("enabled"),
            "communications_mode": (item.get("communications") or {}).get("mode"),
            "routes": len((item.get("communications") or {}).get("routes") or []),
            "steps": len(item.get("recipe_ingredients") or []),
            "updated_at": item.get("updated_at"),
        }
        for item in rows
    ]


def _workflow_detail_table(item: dict[str, Any]) -> str:
    communications = item.get("communications") or {}
    return render_sections(
        [
            (
                "Workflow",
                {
                    "id": item.get("id"),
                    "name": item.get("name"),
                    "description": item.get("description"),
                    "enabled": item.get("enabled"),
                    "clear_timeout_sec": item.get("clear_timeout_sec"),
                    "communications_mode": communications.get("mode"),
                    "communications_source": communications.get("effective_source"),
                    "updated_at": item.get("updated_at"),
                },
            ),
            (
                "Communication Routes",
                [
                    {
                        "id": route.get("id"),
                        "label": route.get("label"),
                        "target": route.get("execution_target"),
                        "destination": route.get("destination_target"),
                        "enabled": route.get("enabled"),
                        "position": route.get("position"),
                    }
                    for route in communications.get("routes") or []
                ],
            ),
            (
                "Steps",
                [
                    {
                        "step_order": step.get("step_order"),
                        "ingredient_id": step.get("ingredient_id"),
                        "on_success": step.get("on_success"),
                        "run_phase": step.get("run_phase"),
                        "run_condition": step.get("run_condition"),
                        "parallel_group": step.get("parallel_group"),
                        "depth": step.get("depth"),
                    }
                    for step in item.get("recipe_ingredients") or []
                ],
            ),
        ]
    )


def _normalize_step(step: dict[str, Any], *, index: int) -> dict[str, Any]:
    ingredient_id = step.get("ingredient_id")
    if ingredient_id is None:
        raise click.BadParameter("Each step must include ingredient_id")
    return {
        "ingredient_id": int(ingredient_id),
        "step_order": index,
        "on_success": step.get("on_success", "continue"),
        "parallel_group": int(step.get("parallel_group", 0)),
        "depth": int(step.get("depth", 0)),
        "execution_parameters_override": step.get("execution_parameters_override"),
        "run_phase": step.get("run_phase", "both"),
        "run_condition": step.get("run_condition", "always"),
    }


def _normalize_route(route: dict[str, Any], *, index: int) -> dict[str, Any]:
    label = route.get("label")
    execution_target = route.get("execution_target")
    if not label or not execution_target:
        raise click.BadParameter("Each route must include label and execution_target")
    normalized = {
        "label": label,
        "execution_target": execution_target,
        "destination_target": route.get("destination_target", ""),
        "provider_config": route.get("provider_config", {}),
        "enabled": bool(route.get("enabled", True)),
        "position": index,
    }
    if route.get("id") is not None:
        normalized["id"] = route["id"]
    return normalized


def _ensure_file_is_exclusive(file: Path | None, inline_values: list[Any]) -> None:
    if file is None:
        return
    if any(value not in (None, "", (), []) for value in inline_values):
        raise click.BadParameter("--file cannot be combined with inline workflow options")


def _validate_non_communication_steps(client: PoundCakeClient, steps: list[dict[str, Any]]) -> None:
    ingredient_ids = sorted({int(step["ingredient_id"]) for step in steps})
    for ingredient_id in ingredient_ids:
        ingredient = client.get_ingredient(ingredient_id)
        if (
            ingredient.get("execution_engine") == "bakery"
            and ingredient.get("execution_purpose") == "comms"
        ):
            raise click.BadParameter(
                f"Ingredient {ingredient_id} is a managed communication action and cannot be used as a workflow step"
            )


def _build_workflow_payload(
    client: PoundCakeClient,
    *,
    file: Path | None,
    name: str | None,
    description: str | None,
    enabled: bool | None,
    clear_timeout_sec: int | None,
    communications_mode: str | None,
    step_json: tuple[str, ...],
    route_json: tuple[str, ...],
    creating: bool,
) -> dict[str, Any]:
    _ensure_file_is_exclusive(
        file,
        [
            name,
            description,
            enabled,
            clear_timeout_sec,
            communications_mode,
            step_json,
            route_json,
        ],
    )
    if file is not None:
        payload = read_mapping_file(file, "workflow file")
        step_items = payload.get("recipe_ingredients") or []
        if not isinstance(step_items, list):
            raise click.BadParameter("workflow file recipe_ingredients must be a list")
        normalized_steps = [
            _normalize_step(item, index=index + 1) for index, item in enumerate(step_items)
        ]
        if normalized_steps:
            _validate_non_communication_steps(client, normalized_steps)
            payload["recipe_ingredients"] = normalized_steps
        communications = payload.get("communications")
        if isinstance(communications, dict):
            routes = communications.get("routes") or []
            if not isinstance(routes, list):
                raise click.BadParameter("workflow file communications.routes must be a list")
            payload["communications"] = {
                "mode": communications.get("mode", "inherit"),
                "routes": [
                    _normalize_route(item, index=index + 1) for index, item in enumerate(routes)
                ],
            }
        return payload

    parsed_steps = [
        _normalize_step(parse_json_object(raw, "step-json") or {}, index=index + 1)
        for index, raw in enumerate(step_json)
    ]
    parsed_routes = [
        _normalize_route(parse_json_object(raw, "route-json") or {}, index=index + 1)
        for index, raw in enumerate(route_json)
    ]
    if parsed_steps:
        _validate_non_communication_steps(client, parsed_steps)
    resolved_mode = communications_mode
    if resolved_mode is None and parsed_routes:
        resolved_mode = "local"
    if resolved_mode is None and creating:
        resolved_mode = "inherit"

    payload = compact_update_payload(
        {
            "name": name,
            "description": description,
            "enabled": enabled,
            "clear_timeout_sec": clear_timeout_sec,
        }
    )
    if creating and "enabled" not in payload:
        payload["enabled"] = True
    if parsed_steps:
        payload["recipe_ingredients"] = parsed_steps
    elif creating:
        raise click.BadParameter("At least one --step-json is required when creating a workflow")

    if resolved_mode is not None or parsed_routes:
        payload["communications"] = {
            "mode": resolved_mode or "local",
            "routes": parsed_routes if (resolved_mode or "local") == "local" else [],
        }
    return payload


@click.group(name="workflows")
def workflows() -> None:
    """Manage workflows."""


@workflows.command("list")
@click.option("--name", default=None)
@click.option("--enabled", "enabled_filter", flag_value=True, default=None)
@click.option("--disabled", "enabled_filter", flag_value=False)
@click.option("--limit", type=int, default=500, show_default=True)
@click.option("--offset", type=int, default=0, show_default=True)
@click.pass_context
def list_workflows(
    ctx: click.Context,
    name: str | None,
    enabled_filter: bool | None,
    limit: int,
    offset: int,
) -> None:
    """List workflows."""
    client = get_client(ctx)
    output_format = get_output_format(ctx)
    try:
        payload = client.list_recipes(name=name, enabled=enabled_filter, limit=limit, offset=offset)
        if output_format == "table":
            print_output(_workflow_rows(payload), output_format)
            return
        print_output(payload, output_format)
    except PoundCakeClientError as exc:
        print_error(f"Failed to list workflows: {exc}")
        raise click.Abort() from exc


@workflows.command("get")
@click.argument("workflow_id", type=int)
@click.pass_context
def get_workflow(ctx: click.Context, workflow_id: int) -> None:
    """Get one workflow."""
    client = get_client(ctx)
    output_format = get_output_format(ctx)
    try:
        payload = client.get_recipe(workflow_id)
        print_output(payload, output_format, table_renderer=_workflow_detail_table)
    except PoundCakeClientError as exc:
        print_error(f"Failed to get workflow: {exc}")
        raise click.Abort() from exc


@workflows.command("create")
@click.option(
    "--file",
    type=click.Path(exists=True, path_type=Path),
    default=None,
    help="JSON or YAML workflow payload",
)
@click.option("--name", default=None)
@click.option("--description", default=None)
@click.option("--enabled", "enabled_value", flag_value=True, default=None)
@click.option("--disabled", "enabled_value", flag_value=False)
@click.option("--clear-timeout-sec", type=int, default=None)
@click.option("--communications-mode", type=click.Choice(["inherit", "local"]), default=None)
@click.option("--step-json", multiple=True, help="JSON object describing one workflow step")
@click.option("--route-json", multiple=True, help="JSON object describing one communication route")
@click.pass_context
def create_workflow(
    ctx: click.Context,
    file: Path | None,
    name: str | None,
    description: str | None,
    enabled_value: bool | None,
    clear_timeout_sec: int | None,
    communications_mode: str | None,
    step_json: tuple[str, ...],
    route_json: tuple[str, ...],
) -> None:
    """Create a workflow."""
    client = get_client(ctx)
    output_format = get_output_format(ctx)
    try:
        payload = _build_workflow_payload(
            client,
            file=file,
            name=name,
            description=description,
            enabled=enabled_value,
            clear_timeout_sec=clear_timeout_sec,
            communications_mode=communications_mode,
            step_json=step_json,
            route_json=route_json,
            creating=True,
        )
        response = client.create_recipe(payload)
        print_output(response, output_format, table_renderer=_workflow_detail_table)
    except (click.BadParameter, PoundCakeClientError) as exc:
        print_error(f"Failed to create workflow: {exc}")
        raise click.Abort() from exc


@workflows.command("update")
@click.argument("workflow_id", type=int)
@click.option(
    "--file",
    type=click.Path(exists=True, path_type=Path),
    default=None,
    help="JSON or YAML workflow payload",
)
@click.option("--name", default=None)
@click.option("--description", default=None)
@click.option("--enabled", "enabled_value", flag_value=True, default=None)
@click.option("--disabled", "enabled_value", flag_value=False)
@click.option("--clear-timeout-sec", type=int, default=None)
@click.option("--communications-mode", type=click.Choice(["inherit", "local"]), default=None)
@click.option("--step-json", multiple=True, help="JSON object describing one workflow step")
@click.option("--route-json", multiple=True, help="JSON object describing one communication route")
@click.pass_context
def update_workflow(
    ctx: click.Context,
    workflow_id: int,
    file: Path | None,
    name: str | None,
    description: str | None,
    enabled_value: bool | None,
    clear_timeout_sec: int | None,
    communications_mode: str | None,
    step_json: tuple[str, ...],
    route_json: tuple[str, ...],
) -> None:
    """Update a workflow."""
    client = get_client(ctx)
    output_format = get_output_format(ctx)
    try:
        payload = _build_workflow_payload(
            client,
            file=file,
            name=name,
            description=description,
            enabled=enabled_value,
            clear_timeout_sec=clear_timeout_sec,
            communications_mode=communications_mode,
            step_json=step_json,
            route_json=route_json,
            creating=False,
        )
        if not payload:
            raise click.BadParameter("No update fields provided")
        response = client.update_recipe(workflow_id, payload)
        print_output(response, output_format, table_renderer=_workflow_detail_table)
    except (click.BadParameter, PoundCakeClientError) as exc:
        print_error(f"Failed to update workflow: {exc}")
        raise click.Abort() from exc


@workflows.command("delete")
@click.argument("workflow_id", type=int)
@click.option("--yes", is_flag=True, help="Skip confirmation prompt")
@click.pass_context
def delete_workflow(ctx: click.Context, workflow_id: int, yes: bool) -> None:
    """Delete a workflow."""
    client = get_client(ctx)
    output_format = get_output_format(ctx)
    try:
        workflow = client.get_recipe(workflow_id)
        if not yes:
            click.confirm(f"Delete workflow '{workflow.get('name') or workflow_id}'?", abort=True)
        response = client.delete_recipe(workflow_id)
        print_output(response, output_format)
    except PoundCakeClientError as exc:
        print_error(f"Failed to delete workflow: {exc}")
        raise click.Abort() from exc
