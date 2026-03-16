"""Authentication commands for the PoundCake CLI."""

from __future__ import annotations

import click

from cli.client import PoundCakeClientError
from cli.commands.common import get_client, get_output_format
from cli.utils import print_error, print_output, print_success


@click.group()
def auth() -> None:
    """Manage CLI authentication."""


@auth.command("login")
@click.option("--username", default=None, help="PoundCake username")
@click.option("--password", default=None, help="PoundCake password")
@click.pass_context
def login_cmd(ctx: click.Context, username: str | None, password: str | None) -> None:
    """Log in with username/password and persist the session locally."""
    client = get_client(ctx)
    output_format = get_output_format(ctx)
    try:
        final_username = username or click.prompt("Username", type=str)
        final_password = password or click.prompt("Password", hide_input=True, type=str)
        result = client.login(final_username, final_password)
        print_output(
            {
                "username": result.username,
                "expires_at": result.expires_at,
                "token_type": result.token_type,
            },
            output_format,
        )
    except PoundCakeClientError as exc:
        print_error(f"Login failed: {exc}")
        raise click.Abort() from exc


@auth.command("logout")
@click.pass_context
def logout_cmd(ctx: click.Context) -> None:
    """Clear the local session and attempt remote logout."""
    client = get_client(ctx)
    try:
        had_session = client.logout()
        if had_session:
            print_success("Logged out and cleared stored session.")
        else:
            print_success("No stored session was present.")
    except PoundCakeClientError as exc:
        print_error(f"Logout failed: {exc}")
        raise click.Abort() from exc
