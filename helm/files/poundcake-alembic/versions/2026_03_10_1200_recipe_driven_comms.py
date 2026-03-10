"""recipe_driven_comms

Revision ID: 2026_03_10_1200
Revises: 2026_02_03_1600
Create Date: 2026-03-10 12:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "2026_03_10_1200"
down_revision: Union[str, None] = "2026_02_03_1600"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("recipes", sa.Column("clear_timeout_sec", sa.Integer(), nullable=True))

    op.add_column(
        "recipe_ingredients",
        sa.Column(
            "run_condition",
            sa.String(length=40),
            nullable=False,
            server_default="always",
        ),
    )
    op.alter_column("recipe_ingredients", "run_condition", server_default=None)

    op.add_column(
        "ingredients",
        sa.Column(
            "destination_target",
            sa.String(length=255),
            nullable=False,
            server_default="",
        ),
    )
    op.drop_index("ux_ingredients_engine_target", table_name="ingredients")
    op.create_index(
        "ux_ingredients_engine_target",
        "ingredients",
        ["execution_engine", "execution_target", "destination_target", "task_key_template"],
        unique=True,
    )

    op.add_column(
        "dish_ingredients",
        sa.Column("destination_target", sa.String(length=255), nullable=True),
    )

    op.add_column(
        "orders",
        sa.Column(
            "remediation_outcome",
            sa.String(length=16),
            nullable=False,
            server_default="pending",
        ),
    )
    op.add_column("orders", sa.Column("clear_timeout_sec", sa.Integer(), nullable=True))
    op.add_column("orders", sa.Column("clear_deadline_at", sa.DateTime(), nullable=True))
    op.add_column("orders", sa.Column("clear_timed_out_at", sa.DateTime(), nullable=True))
    op.add_column(
        "orders",
        sa.Column(
            "auto_close_eligible",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    op.create_index("ix_orders_remediation_outcome", "orders", ["remediation_outcome"], unique=False)
    op.create_index("ix_orders_clear_deadline_at", "orders", ["clear_deadline_at"], unique=False)
    op.create_index("ix_orders_clear_timed_out_at", "orders", ["clear_timed_out_at"], unique=False)
    op.create_index(
        "ix_orders_auto_close_eligible", "orders", ["auto_close_eligible"], unique=False
    )

    op.create_table(
        "order_communications",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("order_id", sa.Integer(), nullable=False),
        sa.Column("execution_target", sa.String(length=100), nullable=False),
        sa.Column("destination_target", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("bakery_ticket_id", sa.String(length=36), nullable=True),
        sa.Column("bakery_operation_id", sa.String(length=36), nullable=True),
        sa.Column("lifecycle_state", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("remote_state", sa.String(length=64), nullable=True),
        sa.Column("writable", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("reopenable", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "order_id",
            "execution_target",
            "destination_target",
            name="ux_order_communications_route",
        ),
    )
    op.create_index("ix_order_communications_id", "order_communications", ["id"], unique=False)
    op.create_index(
        "ix_order_communications_order_id", "order_communications", ["order_id"], unique=False
    )
    op.create_index(
        "ix_order_communications_execution_target",
        "order_communications",
        ["execution_target"],
        unique=False,
    )
    op.create_index(
        "ix_order_communications_bakery_ticket_id",
        "order_communications",
        ["bakery_ticket_id"],
        unique=False,
    )
    op.create_index(
        "ix_order_communications_bakery_operation_id",
        "order_communications",
        ["bakery_operation_id"],
        unique=False,
    )
    op.create_index(
        "ix_order_communications_remote_state",
        "order_communications",
        ["remote_state"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_order_communications_remote_state", table_name="order_communications")
    op.drop_index("ix_order_communications_bakery_operation_id", table_name="order_communications")
    op.drop_index("ix_order_communications_bakery_ticket_id", table_name="order_communications")
    op.drop_index("ix_order_communications_execution_target", table_name="order_communications")
    op.drop_index("ix_order_communications_order_id", table_name="order_communications")
    op.drop_index("ix_order_communications_id", table_name="order_communications")
    op.drop_table("order_communications")

    op.drop_index("ix_orders_auto_close_eligible", table_name="orders")
    op.drop_index("ix_orders_clear_timed_out_at", table_name="orders")
    op.drop_index("ix_orders_clear_deadline_at", table_name="orders")
    op.drop_index("ix_orders_remediation_outcome", table_name="orders")
    op.drop_column("orders", "auto_close_eligible")
    op.drop_column("orders", "clear_timed_out_at")
    op.drop_column("orders", "clear_deadline_at")
    op.drop_column("orders", "clear_timeout_sec")
    op.drop_column("orders", "remediation_outcome")

    op.drop_column("dish_ingredients", "destination_target")

    op.drop_index("ux_ingredients_engine_target", table_name="ingredients")
    op.create_index(
        "ux_ingredients_engine_target",
        "ingredients",
        ["execution_engine", "execution_target"],
        unique=True,
    )
    op.drop_column("ingredients", "destination_target")

    op.drop_column("recipe_ingredients", "run_condition")
    op.drop_column("recipes", "clear_timeout_sec")
