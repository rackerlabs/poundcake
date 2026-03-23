"""Alert rule commands for the PoundCake CLI."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import click
import yaml

from cli.client import NotFoundError, PoundCakeClientError
from cli.commands.common import get_client, get_output_format
from cli.utils import (
    parse_json_object,
    print_error,
    print_info,
    print_output,
    print_success,
    render_sections,
    to_plain_data,
)


def _print_git_result(result: Any) -> None:
    plain = to_plain_data(result)
    git_result = plain.get("git")
    if not isinstance(git_result, dict):
        return
    pr = git_result.get("pull_request", {})
    if isinstance(pr, dict) and pr.get("url"):
        print_info(f"Pull request created: {pr['url']}")


def _merge_objects(
    base: dict[str, Any] | None,
    overlay: dict[str, Any] | None,
) -> dict[str, Any] | None:
    merged = dict(base or {})
    merged.update(overlay or {})
    return merged or None


def _rule_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "name": rule.get("name"),
            "group": rule.get("group"),
            "for": rule.get("duration"),
            "source": rule.get("crd") or rule.get("file"),
            "state": rule.get("state"),
        }
        for rule in payload.get("rules") or []
    ]


def _rule_detail_table(rule: dict[str, Any]) -> str:
    return render_sections(
        [
            (
                "Alert Rule",
                {
                    "name": rule.get("name"),
                    "group": rule.get("group"),
                    "source": rule.get("crd") or rule.get("file"),
                    "duration": rule.get("duration"),
                    "state": rule.get("state"),
                    "health": rule.get("health"),
                },
            ),
            ("Labels", rule.get("labels") or {}),
            ("Annotations", rule.get("annotations") or {}),
            ("Query", rule.get("query") or ""),
        ]
    )


def _build_rule_data(
    *,
    rule_name: str,
    file: Path | None,
    expr: str | None,
    duration: str | None,
    severity: str | None,
    summary: str | None,
    description: str | None,
    labels_json: str | None,
    annotations_json: str | None,
    base_rule: Any | None = None,
) -> dict[str, Any]:
    base_rule_plain = to_plain_data(base_rule) if base_rule is not None else None
    if file:
        loaded = yaml.safe_load(file.read_text(encoding="utf-8"))
        if not isinstance(loaded, dict):
            raise click.BadParameter("Rule file must contain a single rule object")
        return loaded

    if not expr and base_rule is None:
        raise click.BadParameter("Either --file or --expr must be provided")

    labels = _merge_objects(
        (base_rule_plain or {}).get("labels"), parse_json_object(labels_json, "labels-json")
    )
    annotations = _merge_objects(
        (base_rule_plain or {}).get("annotations"),
        parse_json_object(annotations_json, "annotations-json"),
    )
    if severity:
        labels = _merge_objects(labels, {"severity": severity})
    if summary:
        annotations = _merge_objects(annotations, {"summary": summary})
    if description:
        annotations = _merge_objects(annotations, {"description": description})

    payload: dict[str, Any] = {
        "alert": rule_name,
        "expr": expr or (base_rule_plain or {}).get("query"),
    }
    effective_duration = (
        duration or (base_rule_plain or {}).get("duration") or (base_rule_plain or {}).get("for")
    )
    if effective_duration:
        payload["for"] = effective_duration
    if labels:
        payload["labels"] = labels
    if annotations:
        payload["annotations"] = annotations
    return payload


@click.group(name="alert-rules")
def alert_rules() -> None:
    """Manage Prometheus alert rules."""


@alert_rules.command("list")
@click.pass_context
def list_rules_cmd(ctx: click.Context) -> None:
    """List alert rules."""
    client = get_client(ctx)
    output_format = get_output_format(ctx)
    try:
        payload = client.list_rules()
        if output_format == "table":
            print_output(_rule_rows(to_plain_data(payload)), output_format)
            return
        print_output(payload, output_format)
    except PoundCakeClientError as exc:
        print_error(f"Failed to list alert rules: {exc}")
        raise click.Abort() from exc


@alert_rules.command("get")
@click.argument("source_name")
@click.argument("group_name")
@click.argument("rule_name")
@click.pass_context
def get_rule_cmd(ctx: click.Context, source_name: str, group_name: str, rule_name: str) -> None:
    """Get one alert rule."""
    client = get_client(ctx)
    output_format = get_output_format(ctx)
    try:
        payload = client.get_rule(source_name, group_name, rule_name)
        print_output(payload, output_format, table_renderer=_rule_detail_table)
    except PoundCakeClientError as exc:
        print_error(f"Failed to get alert rule: {exc}")
        raise click.Abort() from exc


@alert_rules.command("create")
@click.argument("source_name")
@click.argument("group_name")
@click.argument("rule_name")
@click.option("--file", type=click.Path(exists=True, path_type=Path), default=None)
@click.option("--expr", default=None)
@click.option("--for", "duration", default=None)
@click.option("--severity", default=None)
@click.option("--summary", default=None)
@click.option("--description", default=None)
@click.option("--labels-json", default=None)
@click.option("--annotations-json", default=None)
@click.pass_context
def create_rule_cmd(
    ctx: click.Context,
    source_name: str,
    group_name: str,
    rule_name: str,
    file: Path | None,
    expr: str | None,
    duration: str | None,
    severity: str | None,
    summary: str | None,
    description: str | None,
    labels_json: str | None,
    annotations_json: str | None,
) -> None:
    """Create an alert rule."""
    client = get_client(ctx)
    try:
        rule_data = _build_rule_data(
            rule_name=rule_name,
            file=file,
            expr=expr,
            duration=duration,
            severity=severity,
            summary=summary,
            description=description,
            labels_json=labels_json,
            annotations_json=annotations_json,
        )
        result = client.create_rule(source_name, group_name, rule_name, rule_data)
        print_success(f"Created alert rule: {rule_name}")
        _print_git_result(result)
    except (click.BadParameter, PoundCakeClientError) as exc:
        print_error(f"Failed to create alert rule: {exc}")
        raise click.Abort() from exc


@alert_rules.command("update")
@click.argument("source_name")
@click.argument("group_name")
@click.argument("rule_name")
@click.option("--file", type=click.Path(exists=True, path_type=Path), default=None)
@click.option("--expr", default=None)
@click.option("--for", "duration", default=None)
@click.option("--severity", default=None)
@click.option("--summary", default=None)
@click.option("--description", default=None)
@click.option("--labels-json", default=None)
@click.option("--annotations-json", default=None)
@click.pass_context
def update_rule_cmd(
    ctx: click.Context,
    source_name: str,
    group_name: str,
    rule_name: str,
    file: Path | None,
    expr: str | None,
    duration: str | None,
    severity: str | None,
    summary: str | None,
    description: str | None,
    labels_json: str | None,
    annotations_json: str | None,
) -> None:
    """Update an alert rule."""
    client = get_client(ctx)
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
            labels_json=labels_json,
            annotations_json=annotations_json,
            base_rule=current_rule,
        )
        result = client.update_rule(source_name, group_name, rule_name, rule_data)
        print_success(f"Updated alert rule: {rule_name}")
        _print_git_result(result)
    except (click.BadParameter, PoundCakeClientError) as exc:
        print_error(f"Failed to update alert rule: {exc}")
        raise click.Abort() from exc


@alert_rules.command("delete")
@click.argument("source_name")
@click.argument("group_name")
@click.argument("rule_name")
@click.option("--yes", is_flag=True, help="Skip confirmation prompt")
@click.pass_context
def delete_rule_cmd(
    ctx: click.Context,
    source_name: str,
    group_name: str,
    rule_name: str,
    yes: bool,
) -> None:
    """Delete an alert rule."""
    client = get_client(ctx)
    try:
        if not yes:
            click.confirm(f"Delete alert rule '{rule_name}'?", abort=True)
        result = client.delete_rule(source_name, group_name, rule_name)
        print_success(f"Deleted alert rule: {rule_name}")
        _print_git_result(result)
    except PoundCakeClientError as exc:
        print_error(f"Failed to delete alert rule: {exc}")
        raise click.Abort() from exc


@alert_rules.command("apply")
@click.argument("file", type=click.Path(exists=True, path_type=Path))
@click.option(
    "--source-name", default=None, help="CRD or file name; defaults to the input filename stem"
)
@click.option(
    "--dry-run", is_flag=True, help="Show planned create/update actions without applying changes"
)
@click.pass_context
def apply_rules(ctx: click.Context, file: Path, source_name: str | None, dry_run: bool) -> None:
    """Apply all rules from a Prometheus rule-group file."""
    client = get_client(ctx)
    try:
        data = yaml.safe_load(file.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or "groups" not in data:
            raise click.BadParameter("Invalid rule file: top-level 'groups' is required")

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
                    print_success(f"Updated alert rule: {rule_name}")
                except NotFoundError:
                    result = client.create_rule(effective_source, group_name, rule_name, rule)
                    print_success(f"Created alert rule: {rule_name}")
                _print_git_result(result)
    except (click.BadParameter, PoundCakeClientError) as exc:
        print_error(f"Failed to apply alert rules: {exc}")
        raise click.Abort() from exc
