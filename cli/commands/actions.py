"""Action commands for the PoundCake CLI."""

from __future__ import annotations

from typing import Any

import click

from cli.client import PoundCakeClientError
from cli.commands.common import compact_update_payload, get_client, get_output_format
from cli.utils import (
    filter_by_search,
    parse_json_object,
    print_error,
    print_output,
    render_sections,
)

ACTION_TEMPLATE_PRESETS: dict[str, dict[str, Any]] = {
    "ticket": {
        "execution_engine": "bakery",
        "execution_target": "rackspace_core",
        "execution_purpose": "comms",
        "execution_parameters": {"operation": "open"},
    },
    "chat": {
        "execution_engine": "bakery",
        "execution_target": "teams",
        "execution_purpose": "comms",
        "execution_parameters": {"operation": "notify"},
    },
    "remediation": {
        "execution_engine": "stackstorm",
        "execution_purpose": "remediation",
        "execution_parameters": {},
    },
    "custom": {},
}


def _action_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "id": item.get("id"),
            "name": item.get("task_key_template"),
            "target": item.get("execution_target"),
            "destination": item.get("destination_target"),
            "engine": item.get("execution_engine"),
            "purpose": item.get("execution_purpose"),
            "blocking": item.get("is_blocking"),
            "updated_at": item.get("updated_at"),
        }
        for item in rows
    ]


def _action_detail_table(item: dict[str, Any]) -> str:
    return render_sections(
        [
            (
                "Action",
                {
                    "id": item.get("id"),
                    "name": item.get("task_key_template"),
                    "target": item.get("execution_target"),
                    "destination": item.get("destination_target"),
                    "engine": item.get("execution_engine"),
                    "purpose": item.get("execution_purpose"),
                    "execution_id": item.get("execution_id"),
                    "is_default": item.get("is_default"),
                    "is_blocking": item.get("is_blocking"),
                    "expected_duration_sec": item.get("expected_duration_sec"),
                    "timeout_duration_sec": item.get("timeout_duration_sec"),
                    "retry_count": item.get("retry_count"),
                    "retry_delay": item.get("retry_delay"),
                    "on_failure": item.get("on_failure"),
                    "deleted": item.get("deleted"),
                    "updated_at": item.get("updated_at"),
                },
            ),
            ("Execution Payload", item.get("execution_payload") or {}),
            ("Execution Parameters", item.get("execution_parameters") or {}),
        ]
    )


def _payload_from_template(template: str | None) -> dict[str, Any]:
    if not template:
        return {}
    return {
        key: value.copy() if isinstance(value, dict) else value
        for key, value in ACTION_TEMPLATE_PRESETS[template].items()
    }


def _build_action_payload(
    *,
    template: str | None,
    execution_target: str | None,
    destination_target: str | None,
    task_key_template: str | None,
    execution_engine: str | None,
    execution_purpose: str | None,
    execution_id: str | None,
    is_default: bool | None,
    is_blocking: bool | None,
    expected_duration_sec: int | None,
    timeout_duration_sec: int | None,
    retry_count: int | None,
    retry_delay: int | None,
    on_failure: str | None,
    payload_json: str | None,
    parameters_json: str | None,
) -> dict[str, Any]:
    payload = _payload_from_template(template)
    updates = {
        "execution_target": execution_target,
        "destination_target": destination_target,
        "task_key_template": task_key_template,
        "execution_engine": execution_engine,
        "execution_purpose": execution_purpose,
        "execution_id": execution_id,
        "is_default": is_default,
        "is_blocking": is_blocking,
        "expected_duration_sec": expected_duration_sec,
        "timeout_duration_sec": timeout_duration_sec,
        "retry_count": retry_count,
        "retry_delay": retry_delay,
        "on_failure": on_failure,
    }
    payload.update(compact_update_payload(updates))
    if payload_json is not None:
        payload["execution_payload"] = parse_json_object(payload_json, "payload-json")
    if parameters_json is not None:
        payload["execution_parameters"] = parse_json_object(parameters_json, "parameters-json")
    return compact_update_payload(payload)


@click.group(name="actions")
def actions() -> None:
    """Manage reusable workflow actions."""


@actions.command("list")
@click.option("--execution-target", default=None)
@click.option("--task-key-template", default=None)
@click.option("--search", default=None)
@click.option("--limit", type=int, default=500, show_default=True)
@click.option("--offset", type=int, default=0, show_default=True)
@click.pass_context
def list_actions(
    ctx: click.Context,
    execution_target: str | None,
    task_key_template: str | None,
    search: str | None,
    limit: int,
    offset: int,
) -> None:
    """List actions."""
    client = get_client(ctx)
    output_format = get_output_format(ctx)
    try:
        rows = client.list_ingredients(
            execution_target=execution_target,
            task_key_template=task_key_template,
            limit=limit,
            offset=offset,
        )
        rows = filter_by_search(
            rows, search, ["task_key_template", "execution_target", "destination_target"]
        )
        if output_format == "table":
            print_output(_action_rows(rows), output_format)
            return
        print_output(rows, output_format)
    except PoundCakeClientError as exc:
        print_error(f"Failed to list actions: {exc}")
        raise click.Abort() from exc


@actions.command("get")
@click.argument("action_id", type=int)
@click.pass_context
def get_action(ctx: click.Context, action_id: int) -> None:
    """Get one action."""
    client = get_client(ctx)
    output_format = get_output_format(ctx)
    try:
        payload = client.get_ingredient(action_id)
        print_output(payload, output_format, table_renderer=_action_detail_table)
    except PoundCakeClientError as exc:
        print_error(f"Failed to get action: {exc}")
        raise click.Abort() from exc


@actions.command("create")
@click.option(
    "--template",
    type=click.Choice(["ticket", "chat", "remediation", "custom"]),
    default="remediation",
    show_default=True,
)
@click.option("--execution-target", default=None)
@click.option("--destination-target", default="")
@click.option("--task-key-template", required=True)
@click.option("--execution-engine", default=None)
@click.option("--execution-purpose", default=None)
@click.option("--execution-id", default=None)
@click.option("--is-default/--not-default", default=False, show_default=True)
@click.option("--is-blocking/--non-blocking", default=True, show_default=True)
@click.option("--expected-duration-sec", type=int, required=True)
@click.option("--timeout-duration-sec", type=int, default=300, show_default=True)
@click.option("--retry-count", type=int, default=0, show_default=True)
@click.option("--retry-delay", type=int, default=5, show_default=True)
@click.option(
    "--on-failure",
    type=click.Choice(["stop", "continue", "retry"]),
    default="stop",
    show_default=True,
)
@click.option("--payload-json", default=None)
@click.option("--parameters-json", default=None)
@click.pass_context
def create_action(
    ctx: click.Context,
    template: str,
    execution_target: str | None,
    destination_target: str,
    task_key_template: str,
    execution_engine: str | None,
    execution_purpose: str | None,
    execution_id: str | None,
    is_default: bool,
    is_blocking: bool,
    expected_duration_sec: int,
    timeout_duration_sec: int,
    retry_count: int,
    retry_delay: int,
    on_failure: str,
    payload_json: str | None,
    parameters_json: str | None,
) -> None:
    """Create an action."""
    client = get_client(ctx)
    output_format = get_output_format(ctx)
    try:
        payload = _build_action_payload(
            template=template,
            execution_target=execution_target,
            destination_target=destination_target,
            task_key_template=task_key_template,
            execution_engine=execution_engine,
            execution_purpose=execution_purpose,
            execution_id=execution_id,
            is_default=is_default,
            is_blocking=is_blocking,
            expected_duration_sec=expected_duration_sec,
            timeout_duration_sec=timeout_duration_sec,
            retry_count=retry_count,
            retry_delay=retry_delay,
            on_failure=on_failure,
            payload_json=payload_json,
            parameters_json=parameters_json,
        )
        response = client.create_ingredient(payload)
        print_output(response, output_format, table_renderer=_action_detail_table)
    except PoundCakeClientError as exc:
        print_error(f"Failed to create action: {exc}")
        raise click.Abort() from exc


@actions.command("update")
@click.argument("action_id", type=int)
@click.option(
    "--template", type=click.Choice(["ticket", "chat", "remediation", "custom"]), default=None
)
@click.option("--execution-target", default=None)
@click.option("--destination-target", default=None)
@click.option("--task-key-template", default=None)
@click.option("--execution-engine", default=None)
@click.option("--execution-purpose", default=None)
@click.option("--execution-id", default=None)
@click.option("--is-default/--not-default", default=None)
@click.option("--is-blocking/--non-blocking", default=None)
@click.option("--expected-duration-sec", type=int, default=None)
@click.option("--timeout-duration-sec", type=int, default=None)
@click.option("--retry-count", type=int, default=None)
@click.option("--retry-delay", type=int, default=None)
@click.option("--on-failure", type=click.Choice(["stop", "continue", "retry"]), default=None)
@click.option("--payload-json", default=None)
@click.option("--parameters-json", default=None)
@click.pass_context
def update_action(
    ctx: click.Context,
    action_id: int,
    template: str | None,
    execution_target: str | None,
    destination_target: str | None,
    task_key_template: str | None,
    execution_engine: str | None,
    execution_purpose: str | None,
    execution_id: str | None,
    is_default: bool | None,
    is_blocking: bool | None,
    expected_duration_sec: int | None,
    timeout_duration_sec: int | None,
    retry_count: int | None,
    retry_delay: int | None,
    on_failure: str | None,
    payload_json: str | None,
    parameters_json: str | None,
) -> None:
    """Update an action."""
    client = get_client(ctx)
    output_format = get_output_format(ctx)
    try:
        payload = _build_action_payload(
            template=template,
            execution_target=execution_target,
            destination_target=destination_target,
            task_key_template=task_key_template,
            execution_engine=execution_engine,
            execution_purpose=execution_purpose,
            execution_id=execution_id,
            is_default=is_default,
            is_blocking=is_blocking,
            expected_duration_sec=expected_duration_sec,
            timeout_duration_sec=timeout_duration_sec,
            retry_count=retry_count,
            retry_delay=retry_delay,
            on_failure=on_failure,
            payload_json=payload_json,
            parameters_json=parameters_json,
        )
        if not payload:
            raise click.BadParameter("No update fields provided")
        response = client.update_ingredient(action_id, payload)
        print_output(response, output_format, table_renderer=_action_detail_table)
    except (click.BadParameter, PoundCakeClientError) as exc:
        print_error(f"Failed to update action: {exc}")
        raise click.Abort() from exc


@actions.command("delete")
@click.argument("action_id", type=int)
@click.option("--yes", is_flag=True, help="Skip confirmation prompt")
@click.pass_context
def delete_action(ctx: click.Context, action_id: int, yes: bool) -> None:
    """Delete an action."""
    client = get_client(ctx)
    output_format = get_output_format(ctx)
    try:
        action = client.get_ingredient(action_id)
        if not yes:
            click.confirm(
                f"Delete action '{action.get('task_key_template') or action_id}'?",
                abort=True,
            )
        payload = client.delete_ingredient(action_id)
        if output_format == "table":
            print_output(
                {
                    "status": payload.get("status"),
                    "id": payload.get("id"),
                    "message": payload.get("message"),
                },
                output_format,
            )
            return
        print_output(payload, output_format)
    except PoundCakeClientError as exc:
        print_error(f"Failed to delete action: {exc}")
        raise click.Abort() from exc
