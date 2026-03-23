"""Incident commands for the PoundCake CLI."""

from __future__ import annotations

import time
from typing import Any

import click

from cli.client import PoundCakeClientError
from cli.commands.common import get_client, get_output_format
from cli.utils import (
    filter_by_search,
    print_error,
    print_output,
    print_success,
    render_sections,
    to_plain_data,
)


def _incident_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "id": item.get("id"),
            "name": item.get("alert_group_name"),
            "status": item.get("processing_status"),
            "alert": item.get("alert_status"),
            "severity": item.get("severity"),
            "instance": item.get("instance"),
            "routes": len(item.get("communications") or []),
            "updated_at": item.get("updated_at"),
        }
        for item in rows
    ]


def _incident_detail_table(order: dict[str, Any]) -> str:
    return render_sections(
        [
            (
                "Incident",
                {
                    "id": order.get("id"),
                    "name": order.get("alert_group_name"),
                    "processing_status": order.get("processing_status"),
                    "alert_status": order.get("alert_status"),
                    "severity": order.get("severity"),
                    "instance": order.get("instance"),
                    "req_id": order.get("req_id"),
                    "counter": order.get("counter"),
                    "remediation_outcome": order.get("remediation_outcome"),
                    "auto_close_eligible": order.get("auto_close_eligible"),
                    "starts_at": order.get("starts_at"),
                    "ends_at": order.get("ends_at"),
                    "updated_at": order.get("updated_at"),
                },
            ),
            (
                "Communications",
                [
                    {
                        "id": item.get("id"),
                        "target": item.get("execution_target"),
                        "destination": item.get("destination_target"),
                        "ticket_id": item.get("bakery_ticket_id"),
                        "operation_id": item.get("bakery_operation_id"),
                        "state": item.get("remote_state") or item.get("lifecycle_state"),
                        "writable": item.get("writable"),
                        "reopenable": item.get("reopenable"),
                    }
                    for item in order.get("communications") or []
                ],
            ),
        ]
    )


def _timeline_table(payload: dict[str, Any]) -> str:
    return render_sections(
        [
            ("Incident", _incident_rows([payload["order"]])[0]),
            (
                "Timeline",
                [
                    {
                        "timestamp": item.get("timestamp"),
                        "event_type": item.get("event_type"),
                        "status": item.get("status"),
                        "title": item.get("title"),
                    }
                    for item in payload.get("events") or []
                ],
            ),
        ]
    )


@click.group(name="incidents")
def incidents() -> None:
    """Inspect incidents and their workflow state."""


@incidents.command("list")
@click.option(
    "--processing-status",
    type=click.Choice(
        [
            "new",
            "processing",
            "waiting_clear",
            "escalation",
            "resolving",
            "complete",
            "failed",
            "canceled",
        ]
    ),
    default=None,
)
@click.option("--alert-status", type=click.Choice(["firing", "resolved"]), default=None)
@click.option("--alert-group-name", default=None)
@click.option("--req-id", default=None)
@click.option(
    "--search",
    default=None,
    help="Client-side search across name, instance, severity, and request id",
)
@click.option("--limit", type=int, default=100, show_default=True)
@click.option("--offset", type=int, default=0, show_default=True)
@click.pass_context
def list_incidents(
    ctx: click.Context,
    processing_status: str | None,
    alert_status: str | None,
    alert_group_name: str | None,
    req_id: str | None,
    search: str | None,
    limit: int,
    offset: int,
) -> None:
    """List incidents."""
    client = get_client(ctx)
    output_format = get_output_format(ctx)
    try:
        incidents_data = client.list_orders(
            processing_status=processing_status,
            alert_status=alert_status,
            alert_group_name=alert_group_name,
            req_id=req_id,
            limit=limit,
            offset=offset,
        )
        incidents_data = filter_by_search(
            incidents_data,
            search,
            ["alert_group_name", "instance", "severity", "req_id"],
        )
        if output_format == "table":
            print_output(_incident_rows(to_plain_data(incidents_data)), output_format)
            return
        print_output(incidents_data, output_format)
    except PoundCakeClientError as exc:
        print_error(f"Failed to list incidents: {exc}")
        raise click.Abort() from exc


@incidents.command("get")
@click.argument("incident_id", type=int)
@click.pass_context
def get_incident(ctx: click.Context, incident_id: int) -> None:
    """Get one incident."""
    client = get_client(ctx)
    output_format = get_output_format(ctx)
    try:
        payload = client.get_order(incident_id)
        print_output(payload, output_format, table_renderer=_incident_detail_table)
    except PoundCakeClientError as exc:
        print_error(f"Failed to get incident: {exc}")
        raise click.Abort() from exc


@incidents.command("timeline")
@click.argument("incident_id", type=int)
@click.pass_context
def incident_timeline(ctx: click.Context, incident_id: int) -> None:
    """Show timeline events for an incident."""
    client = get_client(ctx)
    output_format = get_output_format(ctx)
    try:
        payload = client.get_order_timeline(incident_id)
        print_output(payload, output_format, table_renderer=_timeline_table)
    except PoundCakeClientError as exc:
        print_error(f"Failed to get incident timeline: {exc}")
        raise click.Abort() from exc


@incidents.command("watch")
@click.option(
    "--processing-status",
    type=click.Choice(
        [
            "new",
            "processing",
            "waiting_clear",
            "escalation",
            "resolving",
            "complete",
            "failed",
            "canceled",
        ]
    ),
    default=None,
)
@click.option("--alert-status", type=click.Choice(["firing", "resolved"]), default=None)
@click.option("--alert-group-name", default=None)
@click.option("--req-id", default=None)
@click.option("--search", default=None)
@click.option("--limit", type=int, default=25, show_default=True)
@click.option("--offset", type=int, default=0, show_default=True)
@click.option(
    "--interval", type=int, default=5, show_default=True, help="Refresh interval in seconds"
)
@click.option("--once", is_flag=True, help="Render one refresh and exit")
@click.pass_context
def watch_incidents(
    ctx: click.Context,
    processing_status: str | None,
    alert_status: str | None,
    alert_group_name: str | None,
    req_id: str | None,
    search: str | None,
    limit: int,
    offset: int,
    interval: int,
    once: bool,
) -> None:
    """Continuously refresh the incident list."""
    client = get_client(ctx)
    output_format = get_output_format(ctx)
    try:
        while True:
            rows = client.list_orders(
                processing_status=processing_status,
                alert_status=alert_status,
                alert_group_name=alert_group_name,
                req_id=req_id,
                limit=limit,
                offset=offset,
            )
            rows = filter_by_search(
                rows, search, ["alert_group_name", "instance", "severity", "req_id"]
            )
            click.clear()
            click.echo(f"Incidents (refreshed at {time.strftime('%H:%M:%S')})")
            click.echo("=" * 80)
            if output_format == "table":
                print_output(_incident_rows(to_plain_data(rows)), output_format)
            else:
                print_output(rows, output_format)
            if once:
                break
            time.sleep(interval)
    except KeyboardInterrupt:
        print_success("Stopped watching incidents.")
    except PoundCakeClientError as exc:
        print_error(f"Failed to watch incidents: {exc}")
        raise click.Abort() from exc
