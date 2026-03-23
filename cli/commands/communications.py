"""Communication activity commands for the PoundCake CLI."""

from __future__ import annotations

from typing import Any

import click

from cli.client import PoundCakeClientError
from cli.commands.common import get_client, get_output_format
from cli.utils import filter_by_search, print_error, print_output, render_sections, to_plain_data


def _communication_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "id": item.get("communication_id"),
            "reference": item.get("reference_name") or item.get("reference_id"),
            "channel": item.get("channel"),
            "destination": item.get("destination"),
            "ticket_id": item.get("ticket_id") or item.get("provider_reference_id"),
            "status": item.get("remote_state") or item.get("lifecycle_state"),
            "updated_at": item.get("updated_at"),
        }
        for item in rows
    ]


def _communication_detail_table(item: dict[str, Any]) -> str:
    return render_sections(
        [
            (
                "Communication",
                {
                    "id": item.get("communication_id"),
                    "reference_type": item.get("reference_type"),
                    "reference_id": item.get("reference_id"),
                    "reference_name": item.get("reference_name"),
                    "channel": item.get("channel"),
                    "destination": item.get("destination"),
                    "ticket_id": item.get("ticket_id"),
                    "provider_reference_id": item.get("provider_reference_id"),
                    "operation_id": item.get("operation_id"),
                    "lifecycle_state": item.get("lifecycle_state"),
                    "remote_state": item.get("remote_state"),
                    "writable": item.get("writable"),
                    "reopenable": item.get("reopenable"),
                    "last_error": item.get("last_error"),
                    "updated_at": item.get("updated_at"),
                },
            )
        ]
    )


@click.group(name="communications")
def communications() -> None:
    """Inspect outbound communication history."""


@communications.command("list")
@click.option("--status", default=None, help="Filter by lifecycle or remote status")
@click.option("--channel", default=None, help="Filter by communication channel")
@click.option(
    "--search", default=None, help="Client-side search across reference, destination, and ticket id"
)
@click.option("--limit", type=int, default=100, show_default=True)
@click.option("--offset", type=int, default=0, show_default=True)
@click.pass_context
def list_communications_cmd(
    ctx: click.Context,
    status: str | None,
    channel: str | None,
    search: str | None,
    limit: int,
    offset: int,
) -> None:
    """List communication activity."""
    client = get_client(ctx)
    output_format = get_output_format(ctx)
    try:
        rows = client.list_communications(
            status=status, channel=channel, limit=limit, offset=offset
        )
        rows = filter_by_search(
            rows,
            search,
            [
                "reference_name",
                "reference_id",
                "destination",
                "ticket_id",
                "provider_reference_id",
                "channel",
            ],
        )
        if output_format == "table":
            print_output(_communication_rows(to_plain_data(rows)), output_format)
            return
        print_output(rows, output_format)
    except PoundCakeClientError as exc:
        print_error(f"Failed to list communications: {exc}")
        raise click.Abort() from exc


@communications.command("get")
@click.argument("communication_id")
@click.pass_context
def get_communication_cmd(ctx: click.Context, communication_id: str) -> None:
    """Get one communication activity record by id."""
    client = get_client(ctx)
    output_format = get_output_format(ctx)
    try:
        payload = client.get_communication(communication_id)
        print_output(payload, output_format, table_renderer=_communication_detail_table)
    except PoundCakeClientError as exc:
        print_error(f"Failed to get communication: {exc}")
        raise click.Abort() from exc
