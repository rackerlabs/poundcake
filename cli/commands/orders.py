#  ___                        _  ____      _
# |  _ \ ___  _   _ _ __   __| |/ ___|__ _| | _____
# | |_) / _ \| | | | '_ \ / _` | |   / _` | |/ / _ \
# |  __/ (_) | |_| | | | | (_| | |__| (_| |   <  __/
# |_|   \___/ \__,_|_| |_|\__,_|\____\__,_|_|\_\___|
#
"""Order management commands."""

from typing import Optional

import click

from cli.client import PoundCakeClient
from cli.utils import print_error, print_output, print_success


@click.group()
def orders() -> None:
    """Manage orders and remediations."""
    pass


@orders.command()
@click.option(
    "--processing-status",
    "-s",
    type=click.Choice(["new", "processing", "complete", "failed", "canceled"]),
    help="Filter by processing status",
)
@click.option(
    "--alert-status",
    "-a",
    type=click.Choice(["firing", "resolved"]),
    help="Filter by alert status",
)
@click.option(
    "--alert-group-name",
    help="Filter by alert group name",
)
@click.pass_context
def list(
    ctx: click.Context,
    processing_status: Optional[str],
    alert_status: Optional[str],
    alert_group_name: Optional[str],
) -> None:
    """List all orders."""
    client: PoundCakeClient = ctx.obj["client"]
    format: str = ctx.obj["format"]

    try:
        orders = client.list_orders(
            processing_status=processing_status,
            alert_status=alert_status,
            alert_group_name=alert_group_name,
        )
        print_output(orders, format)
    except Exception as e:
        print_error(f"Failed to list orders: {e}")
        raise click.Abort()


@orders.command()
@click.argument("order_id", type=int)
@click.pass_context
def get(ctx: click.Context, order_id: int) -> None:
    """Get details of a specific order by ID."""
    client: PoundCakeClient = ctx.obj["client"]
    format: str = ctx.obj["format"]

    try:
        order = client.get_order(order_id)
        print_output(order, format)
    except Exception as e:
        print_error(f"Failed to get order: {e}")
        raise click.Abort()


@orders.command()
@click.option(
    "--processing-status",
    "-s",
    type=click.Choice(["new", "processing", "complete", "failed", "canceled"]),
    help="Filter by processing status",
)
@click.option(
    "--alert-status",
    "-a",
    type=click.Choice(["firing", "resolved"]),
    help="Filter by alert status",
)
@click.option(
    "--alert-group-name",
    help="Filter by alert group name",
)
@click.option(
    "--watch",
    "-w",
    is_flag=True,
    help="Watch for new orders (refreshes every 5 seconds)",
)
@click.pass_context
def watch(
    ctx: click.Context,
    processing_status: Optional[str],
    alert_status: Optional[str],
    alert_group_name: Optional[str],
    watch: bool,
) -> None:
    """Watch orders in real-time."""
    import time

    client: PoundCakeClient = ctx.obj["client"]
    format: str = ctx.obj["format"]

    try:
        while True:
            click.clear()
            orders = client.list_orders(
                processing_status=processing_status,
                alert_status=alert_status,
                alert_group_name=alert_group_name,
            )
            click.echo(f"Orders (refreshed at {time.strftime('%H:%M:%S')})")
            click.echo("=" * 80)
            print_output(orders, format)
            if not watch:
                break
            time.sleep(5)
    except KeyboardInterrupt:
        print_success("Stopped watching orders")
    except Exception as e:
        print_error(f"Failed to watch orders: {e}")
        raise click.Abort()
