"""Workflow activity commands for the PoundCake CLI."""

from __future__ import annotations

from typing import Any

import click

from cli.client import PoundCakeClientError
from cli.commands.common import get_client, get_output_format
from cli.utils import filter_by_search, print_error, print_output, render_sections, to_plain_data


def _activity_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "id": item.get("id"),
            "workflow": (item.get("recipe") or {}).get("name")
            or f"Workflow #{item.get('recipe_id')}",
            "phase": item.get("run_phase"),
            "processing_status": item.get("processing_status"),
            "execution_status": item.get("execution_status"),
            "execution_ref": item.get("execution_ref"),
            "incident_id": item.get("order_id"),
            "updated_at": item.get("updated_at"),
        }
        for item in rows
    ]


def _activity_detail_table(item: dict[str, Any]) -> str:
    recipe = item.get("recipe") or {}
    return render_sections(
        [
            (
                "Workflow Run",
                {
                    "id": item.get("id"),
                    "workflow": recipe.get("name") or f"Workflow #{item.get('recipe_id')}",
                    "incident_id": item.get("order_id"),
                    "phase": item.get("run_phase"),
                    "processing_status": item.get("processing_status"),
                    "execution_status": item.get("execution_status"),
                    "execution_ref": item.get("execution_ref"),
                    "retry_attempt": item.get("retry_attempt"),
                    "expected_duration_sec": item.get("expected_duration_sec"),
                    "actual_duration_sec": item.get("actual_duration_sec"),
                    "started_at": item.get("started_at"),
                    "completed_at": item.get("completed_at"),
                    "updated_at": item.get("updated_at"),
                    "error_message": item.get("error_message"),
                },
            )
        ]
    )


@click.group(name="activity")
def activity() -> None:
    """Inspect workflow execution activity."""


@activity.command("list")
@click.option(
    "--processing-status",
    type=click.Choice(
        [
            "new",
            "processing",
            "finalizing",
            "complete",
            "failed",
            "abandoned",
            "timeout",
            "canceled",
        ]
    ),
    default=None,
)
@click.option("--req-id", default=None)
@click.option("--order-id", type=int, default=None)
@click.option("--execution-ref", default=None)
@click.option("--phase", default=None, help="Client-side run phase filter")
@click.option(
    "--search",
    default=None,
    help="Client-side search across workflow, incident id, execution ref, and error",
)
@click.option("--limit", type=int, default=100, show_default=True)
@click.option("--offset", type=int, default=0, show_default=True)
@click.pass_context
def list_activity(
    ctx: click.Context,
    processing_status: str | None,
    req_id: str | None,
    order_id: int | None,
    execution_ref: str | None,
    phase: str | None,
    search: str | None,
    limit: int,
    offset: int,
) -> None:
    """List workflow execution activity."""
    client = get_client(ctx)
    output_format = get_output_format(ctx)
    try:
        rows = client.list_dishes(
            processing_status=processing_status,
            req_id=req_id,
            order_id=order_id,
            execution_ref=execution_ref,
            limit=limit,
            offset=offset,
        )
        if phase:
            rows = [item for item in rows if str(item.run_phase or "") == phase]
        rows = filter_by_search(
            rows,
            search,
            ["run_phase", "execution_ref", "error_message", "order_id"],
        )
        if output_format == "table":
            print_output(_activity_rows(to_plain_data(rows)), output_format)
            return
        print_output(rows, output_format)
    except PoundCakeClientError as exc:
        print_error(f"Failed to list activity: {exc}")
        raise click.Abort() from exc


@activity.command("get")
@click.argument("dish_id", type=int)
@click.pass_context
def get_activity(ctx: click.Context, dish_id: int) -> None:
    """Get one workflow run by id."""
    client = get_client(ctx)
    output_format = get_output_format(ctx)
    try:
        payload = client.get_dish(dish_id)
        print_output(payload, output_format, table_renderer=_activity_detail_table)
    except PoundCakeClientError as exc:
        print_error(f"Failed to get workflow run: {exc}")
        raise click.Abort() from exc
