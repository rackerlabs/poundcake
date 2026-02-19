"""Add Bakery ticket/operation tracking fields to orders.

Revision ID: 2026_02_18_1700
Revises: 2026_02_16_2300
Create Date: 2026-02-18 17:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "2026_02_18_1700"
down_revision: Union[str, None] = "2026_02_16_2300"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_names(table_name: str) -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return {col["name"] for col in inspector.get_columns(table_name)}


def _index_names(table_name: str) -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return {idx["name"] for idx in inspector.get_indexes(table_name)}


def upgrade() -> None:
    cols = _column_names("orders")
    if "bakery_ticket_id" not in cols:
        op.add_column("orders", sa.Column("bakery_ticket_id", sa.String(length=36), nullable=True))
    if "bakery_operation_id" not in cols:
        op.add_column(
            "orders",
            sa.Column("bakery_operation_id", sa.String(length=36), nullable=True),
        )

    indexes = _index_names("orders")
    if "ix_orders_bakery_ticket_id" not in indexes:
        op.create_index("ix_orders_bakery_ticket_id", "orders", ["bakery_ticket_id"], unique=False)
    if "ix_orders_bakery_operation_id" not in indexes:
        op.create_index(
            "ix_orders_bakery_operation_id",
            "orders",
            ["bakery_operation_id"],
            unique=False,
        )


def downgrade() -> None:
    indexes = _index_names("orders")
    if "ix_orders_bakery_operation_id" in indexes:
        op.drop_index("ix_orders_bakery_operation_id", table_name="orders")
    if "ix_orders_bakery_ticket_id" in indexes:
        op.drop_index("ix_orders_bakery_ticket_id", table_name="orders")

    cols = _column_names("orders")
    if "bakery_operation_id" in cols:
        op.drop_column("orders", "bakery_operation_id")
    if "bakery_ticket_id" in cols:
        op.drop_column("orders", "bakery_ticket_id")
