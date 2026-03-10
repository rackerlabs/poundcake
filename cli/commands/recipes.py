"""Recipe management commands."""

from __future__ import annotations

import json

import click

from cli.client import PoundCakeClient
from cli.utils import print_error, print_output


def _parse_step(value: str) -> dict:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise click.BadParameter(f"ingredient-link must be valid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise click.BadParameter("ingredient-link must decode to a JSON object")
    return parsed


@click.group()
def recipes() -> None:
    """Manage recipes."""


@recipes.command("list")
@click.pass_context
def list_recipes_cmd(ctx: click.Context) -> None:
    client: PoundCakeClient = ctx.obj["client"]
    output_format: str = ctx.obj["format"]
    print_output(client.list_recipes(), output_format)


@recipes.command("get")
@click.argument("recipe_id", type=int)
@click.pass_context
def get_recipe_cmd(ctx: click.Context, recipe_id: int) -> None:
    client: PoundCakeClient = ctx.obj["client"]
    output_format: str = ctx.obj["format"]
    print_output(client.get_recipe(recipe_id), output_format)


@recipes.command("create")
@click.option("--name", required=True)
@click.option("--description", default=None)
@click.option("--enabled/--disabled", default=True)
@click.option("--clear-timeout-sec", type=int, default=None)
@click.option(
    "--ingredient-link",
    multiple=True,
    help=(
        "Recipe ingredient JSON object. Example: "
        '\'{"ingredient_id":1,"step_order":1,"run_phase":"firing","run_condition":"always"}\''
    ),
)
@click.pass_context
def create_recipe_cmd(
    ctx: click.Context,
    name: str,
    description: str | None,
    enabled: bool,
    clear_timeout_sec: int | None,
    ingredient_link: tuple[str, ...],
) -> None:
    client: PoundCakeClient = ctx.obj["client"]
    output_format: str = ctx.obj["format"]
    steps = [_parse_step(item) for item in ingredient_link]
    if not steps:
        print_error("At least one --ingredient-link is required.")
        raise click.Abort()
    payload = {
        "name": name,
        "description": description,
        "enabled": enabled,
        "clear_timeout_sec": clear_timeout_sec,
        "recipe_ingredients": steps,
    }
    print_output(client.create_recipe(payload), output_format)


@recipes.command("update")
@click.argument("recipe_id", type=int)
@click.option("--name", default=None)
@click.option("--description", default=None)
@click.option("--enabled-state", type=click.Choice(["true", "false"]), default=None)
@click.option("--clear-timeout-sec", type=int, default=None)
@click.pass_context
def update_recipe_cmd(
    ctx: click.Context,
    recipe_id: int,
    name: str | None,
    description: str | None,
    enabled_state: str | None,
    clear_timeout_sec: int | None,
) -> None:
    client: PoundCakeClient = ctx.obj["client"]
    output_format: str = ctx.obj["format"]
    payload = {
        "name": name,
        "description": description,
        "enabled": None if enabled_state is None else enabled_state == "true",
        "clear_timeout_sec": clear_timeout_sec,
    }
    payload = {key: value for key, value in payload.items() if value is not None}
    if not payload:
        print_error("No update fields provided.")
        raise click.Abort()
    print_output(client.update_recipe(recipe_id, payload), output_format)
