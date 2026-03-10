"""Ingredient management commands."""

from __future__ import annotations

import json
from typing import Any

import click

from cli.client import PoundCakeClient
from cli.utils import print_error, print_output


def _parse_json(value: str | None, field_name: str) -> dict | None:
    if not value:
        return None
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise click.BadParameter(f"{field_name} must be valid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise click.BadParameter(f"{field_name} must decode to a JSON object")
    return parsed


@click.group()
def ingredients() -> None:
    """Manage ingredients."""


@ingredients.command("list")
@click.pass_context
def list_ingredients(ctx: click.Context) -> None:
    client: PoundCakeClient = ctx.obj["client"]
    output_format: str = ctx.obj["format"]
    print_output(client.list_ingredients(), output_format)


@ingredients.command("get")
@click.argument("ingredient_id", type=int)
@click.pass_context
def get_ingredient(ctx: click.Context, ingredient_id: int) -> None:
    client: PoundCakeClient = ctx.obj["client"]
    output_format: str = ctx.obj["format"]
    print_output(client.get_ingredient(ingredient_id), output_format)


@ingredients.command("create")
@click.option("--execution-target", required=True)
@click.option("--destination-target", default="")
@click.option("--task-key-template", required=True)
@click.option("--execution-engine", default="undefined")
@click.option("--execution-purpose", default="utility")
@click.option("--execution-id", default=None)
@click.option("--expected-duration-sec", type=int, required=True)
@click.option("--timeout-duration-sec", type=int, default=300)
@click.option("--retry-count", type=int, default=0)
@click.option("--retry-delay", type=int, default=5)
@click.option("--on-failure", default="stop")
@click.option("--payload-json", default=None)
@click.option("--parameters-json", default=None)
@click.pass_context
def create_ingredient_cmd(
    ctx: click.Context,
    execution_target: str,
    destination_target: str,
    task_key_template: str,
    execution_engine: str,
    execution_purpose: str,
    execution_id: str | None,
    expected_duration_sec: int,
    timeout_duration_sec: int,
    retry_count: int,
    retry_delay: int,
    on_failure: str,
    payload_json: str | None,
    parameters_json: str | None,
) -> None:
    client: PoundCakeClient = ctx.obj["client"]
    output_format: str = ctx.obj["format"]
    payload: dict[str, Any] = {
        "execution_target": execution_target,
        "destination_target": destination_target,
        "task_key_template": task_key_template,
        "execution_engine": execution_engine,
        "execution_purpose": execution_purpose,
        "execution_id": execution_id,
        "expected_duration_sec": expected_duration_sec,
        "timeout_duration_sec": timeout_duration_sec,
        "retry_count": retry_count,
        "retry_delay": retry_delay,
        "on_failure": on_failure,
        "execution_payload": _parse_json(payload_json, "payload-json"),
        "execution_parameters": _parse_json(parameters_json, "parameters-json"),
    }
    print_output(client.create_ingredient(payload), output_format)


@ingredients.command("update")
@click.argument("ingredient_id", type=int)
@click.option("--execution-target", default=None)
@click.option("--destination-target", default=None)
@click.option("--task-key-template", default=None)
@click.option("--execution-engine", default=None)
@click.option("--execution-purpose", default=None)
@click.option("--execution-id", default=None)
@click.option("--expected-duration-sec", type=int, default=None)
@click.option("--timeout-duration-sec", type=int, default=None)
@click.option("--retry-count", type=int, default=None)
@click.option("--retry-delay", type=int, default=None)
@click.option("--on-failure", default=None)
@click.option("--payload-json", default=None)
@click.option("--parameters-json", default=None)
@click.pass_context
def update_ingredient_cmd(
    ctx: click.Context,
    ingredient_id: int,
    execution_target: str | None,
    destination_target: str | None,
    task_key_template: str | None,
    execution_engine: str | None,
    execution_purpose: str | None,
    execution_id: str | None,
    expected_duration_sec: int | None,
    timeout_duration_sec: int | None,
    retry_count: int | None,
    retry_delay: int | None,
    on_failure: str | None,
    payload_json: str | None,
    parameters_json: str | None,
) -> None:
    client: PoundCakeClient = ctx.obj["client"]
    output_format: str = ctx.obj["format"]
    payload: dict[str, Any] = {
        "execution_target": execution_target,
        "destination_target": destination_target,
        "task_key_template": task_key_template,
        "execution_engine": execution_engine,
        "execution_purpose": execution_purpose,
        "execution_id": execution_id,
        "expected_duration_sec": expected_duration_sec,
        "timeout_duration_sec": timeout_duration_sec,
        "retry_count": retry_count,
        "retry_delay": retry_delay,
        "on_failure": on_failure,
    }
    if payload_json is not None:
        payload["execution_payload"] = _parse_json(payload_json, "payload-json")
    if parameters_json is not None:
        payload["execution_parameters"] = _parse_json(parameters_json, "parameters-json")
    payload = {key: value for key, value in payload.items() if value is not None}
    if not payload:
        print_error("No update fields provided.")
        raise click.Abort()
    print_output(client.update_ingredient(ingredient_id, payload), output_format)
