"""Global communications policy commands for the PoundCake CLI."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import click

from cli.client import PoundCakeClientError
from cli.commands.common import get_client, get_output_format, read_mapping_file
from cli.utils import parse_json_object, print_error, print_output, render_sections


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


def _policy_table(payload: dict[str, Any]) -> str:
    return render_sections(
        [
            (
                "Policy",
                {
                    "configured": payload.get("configured"),
                    "route_count": len(payload.get("routes") or []),
                },
            ),
            (
                "Routes",
                [
                    {
                        "id": route.get("id"),
                        "label": route.get("label"),
                        "target": route.get("execution_target"),
                        "destination": route.get("destination_target"),
                        "enabled": route.get("enabled"),
                        "position": route.get("position"),
                    }
                    for route in payload.get("routes") or []
                ],
            ),
            ("Lifecycle Summary", payload.get("lifecycle_summary") or {}),
        ]
    )


def _build_policy_payload(file: Path | None, route_json: tuple[str, ...]) -> dict[str, Any]:
    if file is not None and route_json:
        raise click.BadParameter("--file cannot be combined with --route-json")
    if file is not None:
        payload = read_mapping_file(file, "global communications file")
        routes = payload.get("routes") or []
        if not isinstance(routes, list):
            raise click.BadParameter("global communications file routes must be a list")
        return {
            "routes": [
                _normalize_route(route, index=index + 1) for index, route in enumerate(routes)
            ]
        }
    return {
        "routes": [
            _normalize_route(parse_json_object(raw, "route-json") or {}, index=index + 1)
            for index, raw in enumerate(route_json)
        ]
    }


@click.group(name="global-communications")
def global_communications() -> None:
    """Manage the global communications policy."""


@global_communications.command("get")
@click.pass_context
def get_policy(ctx: click.Context) -> None:
    """Get the global communications policy."""
    client = get_client(ctx)
    output_format = get_output_format(ctx)
    try:
        payload = client.get_global_communications_policy()
        print_output(payload, output_format, table_renderer=_policy_table)
    except PoundCakeClientError as exc:
        print_error(f"Failed to get global communications policy: {exc}")
        raise click.Abort() from exc


@global_communications.command("set")
@click.option(
    "--file",
    type=click.Path(exists=True, path_type=Path),
    default=None,
    help="JSON or YAML policy payload",
)
@click.option("--route-json", multiple=True, help="JSON object describing one communication route")
@click.pass_context
def set_policy(ctx: click.Context, file: Path | None, route_json: tuple[str, ...]) -> None:
    """Set the global communications policy."""
    client = get_client(ctx)
    output_format = get_output_format(ctx)
    try:
        payload = _build_policy_payload(file, route_json)
        response = client.set_global_communications_policy(payload)
        print_output(response, output_format, table_renderer=_policy_table)
    except (click.BadParameter, PoundCakeClientError) as exc:
        print_error(f"Failed to set global communications policy: {exc}")
        raise click.Abort() from exc
