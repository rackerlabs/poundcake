#  ___                        _  ____      _
# |  _ \ ___  _   _ _ __   __| |/ ___|__ _| | _____
# | |_) / _ \| | | | '_ \ / _` | |   / _` | |/ / _ \
# |  __/ (_) | |_| | | | | (_| | |__| (_| |   <  __/
# |_|   \___/ \__,_|_| |_|\__,_|\____\__,_|_|\_\___|
#
"""Main CLI entry point for PoundCake CLI."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

import click

# Support installed console scripts plus legacy module/direct-script execution.
if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cli.client import PoundCakeClient
from cli.commands import (
    actions,
    activity,
    alert_rules,
    auth,
    communications,
    global_communications,
    incidents,
    overview,
    suppressions,
    workflows,
)


@click.group()
@click.option(
    "--url",
    "-u",
    envvar="POUNDCAKE_URL",
    default="http://localhost:8080",
    help="PoundCake API URL",
)
@click.option(
    "--api-key",
    "-k",
    envvar="POUNDCAKE_API_KEY",
    help="API key for authentication (if required)",
)
@click.option(
    "--format",
    "-f",
    type=click.Choice(["json", "yaml", "table"]),
    default="table",
    help="Output format",
)
@click.option(
    "--verbose",
    "-v",
    is_flag=True,
    help="Enable verbose output",
)
@click.pass_context
def cli(
    ctx: click.Context,
    url: str,
    api_key: Optional[str],
    format: str,
    verbose: bool,
) -> None:
    """PoundCake CLI - operate incidents, workflows, and communications."""
    ctx.ensure_object(dict)
    ctx.obj["client"] = PoundCakeClient(url, api_key)
    ctx.obj["format"] = format
    ctx.obj["verbose"] = verbose


cli.add_command(auth.auth)
cli.add_command(overview.overview)
cli.add_command(incidents.incidents)
cli.add_command(communications.communications)
cli.add_command(suppressions.suppressions)
cli.add_command(activity.activity)
cli.add_command(alert_rules.alert_rules)
cli.add_command(global_communications.global_communications)
cli.add_command(workflows.workflows)
cli.add_command(actions.actions)

# Backward-compatible aliases
cli.add_command(incidents.incidents, name="orders")
cli.add_command(alert_rules.alert_rules, name="rules")
cli.add_command(workflows.workflows, name="recipes")
cli.add_command(actions.actions, name="ingredients")


def main() -> None:
    """Main entry point for the CLI."""
    try:
        cli(obj={})
    except Exception as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
