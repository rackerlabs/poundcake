#  ___                        _  ____      _
# |  _ \ ___  _   _ _ __   __| |/ ___|__ _| | _____
# | |_) / _ \| | | | '_ \ / _` | |   / _` | |/ / _ \
# |  __/ (_) | |_| | | | | (_| | |__| (_| |   <  __/
# |_|   \___/ \__,_|_| |_|\__,_|\____\__,_|_|\_\___|
#
"""Prometheus rule management commands."""

from pathlib import Path
from typing import Any, Optional

import click
import yaml

from cli.client import PoundCakeClient
from cli.utils import print_error, print_info, print_output, print_success


def _print_git_result(result: dict[str, Any]) -> None:
    pr = result.get("git", {}).get("pull_request", {})
    if isinstance(pr, dict) and pr.get("url"):
        print_info(f"Pull request created: {pr['url']}")


def _build_rule_data(
    *,
    rule_name: str,
    file: Optional[Path],
    expr: Optional[str],
    duration: Optional[str],
    severity: Optional[str],
    summary: Optional[str],
    description: Optional[str],
    base_rule: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    if file:
        with file.open() as handle:
            loaded = yaml.safe_load(handle)
        if not isinstance(loaded, dict):
            raise ValueError("Rule file must contain a single rule object")
        return loaded

    if not expr:
        raise ValueError("Either --file or --expr must be provided")

    payload: dict[str, Any] = {
        "alert": rule_name,
        "expr": expr,
    }

    effective_duration = (
        duration or (base_rule or {}).get("duration") or (base_rule or {}).get("for")
    )
    if effective_duration:
        payload["for"] = effective_duration

    labels = dict((base_rule or {}).get("labels") or {})
    annotations = dict((base_rule or {}).get("annotations") or {})

    if severity:
        labels["severity"] = severity
    if summary:
        annotations["summary"] = summary
    if description:
        annotations["description"] = description

    if labels:
        payload["labels"] = labels
    if annotations:
        payload["annotations"] = annotations

    return payload


@click.group()
def rules() -> None:
    """Manage Prometheus alert rules."""
    pass


@rules.command()
@click.pass_context
def list(ctx: click.Context) -> None:
    """List all Prometheus rules."""
    client: PoundCakeClient = ctx.obj["client"]
    format: str = ctx.obj["format"]

    try:
        all_rules = client.list_rules()
        print_output(all_rules, format)
    except Exception as e:
        print_error(f"Failed to list rules: {e}")
        raise click.Abort()


@rules.command()
@click.argument("source_name")
@click.argument("group_name")
@click.argument("rule_name")
@click.pass_context
def get(
    ctx: click.Context,
    source_name: str,
    group_name: str,
    rule_name: str,
) -> None:
    """Get a specific rule by source (CRD/file), group, and name."""
    client: PoundCakeClient = ctx.obj["client"]
    format: str = ctx.obj["format"]

    try:
        rule = client.get_rule(source_name, group_name, rule_name)
        print_output(rule, format)
    except Exception as e:
        print_error(f"Failed to get rule: {e}")
        raise click.Abort()


@rules.command()
@click.argument("source_name")
@click.argument("group_name")
@click.argument("rule_name")
@click.option(
    "--file",
    "-f",
    type=click.Path(exists=True, path_type=Path),
    help="YAML file containing rule definition",
)
@click.option(
    "--expr",
    help="PromQL expression for the alert",
)
@click.option(
    "--for",
    "duration",
    help="Duration before alert fires (e.g., 5m, 1h)",
)
@click.option(
    "--severity",
    help="Alert severity label",
)
@click.option(
    "--summary",
    help="Alert summary annotation",
)
@click.option(
    "--description",
    help="Alert description annotation",
)
@click.pass_context
def create(
    ctx: click.Context,
    source_name: str,
    group_name: str,
    rule_name: str,
    file: Optional[Path],
    expr: Optional[str],
    duration: Optional[str],
    severity: Optional[str],
    summary: Optional[str],
    description: Optional[str],
) -> None:
    """Create a new Prometheus rule."""
    client: PoundCakeClient = ctx.obj["client"]

    try:
        rule_data = _build_rule_data(
            rule_name=rule_name,
            file=file,
            expr=expr,
            duration=duration,
            severity=severity,
            summary=summary,
            description=description,
        )

        result = client.create_rule(source_name, group_name, rule_name, rule_data)
        print_success(f"Created rule: {rule_name}")
        _print_git_result(result)

    except Exception as e:
        print_error(f"Failed to create rule: {e}")
        raise click.Abort()


@rules.command()
@click.argument("source_name")
@click.argument("group_name")
@click.argument("rule_name")
@click.option(
    "--file",
    "-f",
    type=click.Path(exists=True, path_type=Path),
    help="YAML file containing updated rule definition",
)
@click.option(
    "--expr",
    help="PromQL expression for the alert",
)
@click.option(
    "--for",
    "duration",
    help="Duration before alert fires (e.g., 5m, 1h)",
)
@click.option(
    "--severity",
    help="Alert severity label",
)
@click.option(
    "--summary",
    help="Alert summary annotation",
)
@click.option(
    "--description",
    help="Alert description annotation",
)
@click.pass_context
def update(
    ctx: click.Context,
    source_name: str,
    group_name: str,
    rule_name: str,
    file: Optional[Path],
    expr: Optional[str],
    duration: Optional[str],
    severity: Optional[str],
    summary: Optional[str],
    description: Optional[str],
) -> None:
    """Update an existing Prometheus rule."""
    client: PoundCakeClient = ctx.obj["client"]

    try:
        current_rule = client.get_rule(source_name, group_name, rule_name)
        rule_data = _build_rule_data(
            rule_name=rule_name,
            file=file,
            expr=expr,
            duration=duration,
            severity=severity,
            summary=summary,
            description=description,
            base_rule=current_rule,
        )

        result = client.update_rule(source_name, group_name, rule_name, rule_data)
        print_success(f"Updated rule: {rule_name}")
        _print_git_result(result)

    except Exception as e:
        print_error(f"Failed to update rule: {e}")
        raise click.Abort()


@rules.command()
@click.argument("source_name")
@click.argument("group_name")
@click.argument("rule_name")
@click.option(
    "--yes",
    "-y",
    is_flag=True,
    help="Skip confirmation prompt",
)
@click.pass_context
def delete(
    ctx: click.Context,
    source_name: str,
    group_name: str,
    rule_name: str,
    yes: bool,
) -> None:
    """Delete a Prometheus rule."""
    client: PoundCakeClient = ctx.obj["client"]

    if not yes:
        click.confirm(
            f"Are you sure you want to delete rule '{rule_name}'?",
            abort=True,
        )

    try:
        result = client.delete_rule(source_name, group_name, rule_name)
        print_success(f"Deleted rule: {rule_name}")
        _print_git_result(result)

    except Exception as e:
        print_error(f"Failed to delete rule: {e}")
        raise click.Abort()


@rules.command()
@click.argument(
    "file",
    type=click.Path(exists=True, path_type=Path),
)
@click.option(
    "--source-name",
    help="CRD or file name (defaults to input filename without extension)",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Show what would be created/updated without applying changes",
)
@click.pass_context
def apply(
    ctx: click.Context,
    file: Path,
    source_name: Optional[str],
    dry_run: bool,
) -> None:
    """Apply rules from a Prometheus rule-group YAML file."""
    client: PoundCakeClient = ctx.obj["client"]

    try:
        with file.open() as handle:
            data = yaml.safe_load(handle)

        if not isinstance(data, dict) or "groups" not in data:
            raise ValueError("Invalid rule file: top-level 'groups' is required")

        effective_source = source_name or file.stem

        for group in data["groups"]:
            group_name = group["name"]
            for rule in group.get("rules", []):
                rule_name = rule.get("alert")
                if not rule_name:
                    continue

                if dry_run:
                    print_info(f"Would create/update: {effective_source}/{group_name}/{rule_name}")
                    continue

                try:
                    client.get_rule(effective_source, group_name, rule_name)
                    result = client.update_rule(effective_source, group_name, rule_name, rule)
                    print_success(f"Updated rule: {rule_name}")
                except ValueError:
                    result = client.create_rule(effective_source, group_name, rule_name, rule)
                    print_success(f"Created rule: {rule_name}")

                _print_git_result(result)

    except Exception as e:
        print_error(f"Failed to apply rules: {e}")
        raise click.Abort()
