"""initial_schema

Revision ID: 2026_02_03_1600
Revises:
Create Date: 2026-02-03 16:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

# revision identifiers, used by Alembic.
revision: str = "2026_02_03_1600"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Recipes
    op.create_table(
        "recipes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("workflow_id", sa.String(length=255), nullable=True),
        sa.Column("workflow_payload", mysql.JSON(), nullable=True),
        sa.Column("workflow_parameters", mysql.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("deleted", sa.Boolean(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_recipes_id"), "recipes", ["id"], unique=False)
    op.create_index(op.f("ix_recipes_name"), "recipes", ["name"], unique=True)

    # Ingredients (global)
    op.create_table(
        "ingredients",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.String(length=100), nullable=False),
        sa.Column("task_name", sa.String(length=255), nullable=False),
        sa.Column("action_id", sa.String(length=100), nullable=True),
        sa.Column("action_payload", sa.Text(), nullable=True),
        sa.Column("action_parameters", mysql.JSON(), nullable=True),
        sa.Column("is_blocking", sa.Boolean(), nullable=False),
        sa.Column("expected_duration_sec", sa.Integer(), nullable=False),
        sa.Column("timeout_duration_sec", sa.Integer(), nullable=False),
        sa.Column("retry_count", sa.Integer(), nullable=False),
        sa.Column("retry_delay", sa.Integer(), nullable=False),
        sa.Column("on_failure", sa.String(length=50), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("deleted", sa.Boolean(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_ingredients_id"), "ingredients", ["id"], unique=False)
    op.create_index(op.f("ix_ingredients_task_id"), "ingredients", ["task_id"], unique=False)

    # Recipe Ingredients (junction)
    op.create_table(
        "recipe_ingredients",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("recipe_id", sa.Integer(), nullable=False),
        sa.Column("ingredient_id", sa.Integer(), nullable=False),
        sa.Column("step_order", sa.Integer(), nullable=False),
        sa.Column("on_success", sa.String(length=50), nullable=False, server_default="continue"),
        sa.Column("parallel_group", sa.Integer(), nullable=False),
        sa.Column("depth", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["ingredient_id"], ["ingredients.id"]),
        sa.ForeignKeyConstraint(["recipe_id"], ["recipes.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_recipe_ingredients_id"), "recipe_ingredients", ["id"], unique=False)
    op.create_index(
        "idx_recipe_ingredient_order",
        "recipe_ingredients",
        ["recipe_id", "step_order"],
        unique=False,
    )

    # Orders (old alerts)
    op.create_table(
        "orders",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("req_id", sa.String(length=100), nullable=False),
        sa.Column("fingerprint", sa.String(length=255), nullable=False),
        sa.Column("alert_status", sa.String(length=50), nullable=False),
        sa.Column("processing_status", sa.String(length=50), nullable=False),
        sa.Column("alert_group_name", sa.String(length=255), nullable=False),
        sa.Column("severity", sa.String(length=50), nullable=True),
        sa.Column("instance", sa.String(length=255), nullable=True),
        sa.Column("counter", sa.Integer(), nullable=False),
        sa.Column("labels", mysql.JSON(), nullable=False),
        sa.Column("annotations", mysql.JSON(), nullable=True),
        sa.Column("raw_data", mysql.JSON(), nullable=True),
        sa.Column("starts_at", sa.DateTime(), nullable=False),
        sa.Column("ends_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_orders_id"), "orders", ["id"], unique=False)
    op.create_index(op.f("ix_orders_req_id"), "orders", ["req_id"], unique=False)
    op.create_index(op.f("ix_orders_fingerprint"), "orders", ["fingerprint"], unique=False)
    op.create_index(op.f("ix_orders_alert_status"), "orders", ["alert_status"], unique=False)
    op.create_index(
        op.f("ix_orders_processing_status"), "orders", ["processing_status"], unique=False
    )
    op.create_index(
        op.f("ix_orders_alert_group_name"), "orders", ["alert_group_name"], unique=False
    )
    op.create_index(op.f("ix_orders_severity"), "orders", ["severity"], unique=False)
    op.create_index(op.f("ix_orders_instance"), "orders", ["instance"], unique=False)
    op.create_index(op.f("ix_orders_created_at"), "orders", ["created_at"], unique=False)

    # Dishes (old ovens)
    op.create_table(
        "dishes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("req_id", sa.String(length=100), nullable=False),
        sa.Column("workflow_execution_id", sa.String(length=100), nullable=True),
        sa.Column("order_id", sa.Integer(), nullable=True),
        sa.Column("recipe_id", sa.Integer(), nullable=False),
        sa.Column("processing_status", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("expected_duration_sec", sa.Integer(), nullable=True),
        sa.Column("actual_duration_sec", sa.Integer(), nullable=True),
        sa.Column("result", mysql.JSON(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("retry_attempt", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"]),
        sa.ForeignKeyConstraint(["recipe_id"], ["recipes.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_dishes_id"), "dishes", ["id"], unique=False)
    op.create_index(op.f("ix_dishes_req_id"), "dishes", ["req_id"], unique=False)
    op.create_index(
        op.f("ix_dishes_workflow_execution_id"),
        "dishes",
        ["workflow_execution_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_dishes_processing_status"), "dishes", ["processing_status"], unique=False
    )

    # Dish Ingredients (per-task executions)
    op.create_table(
        "dish_ingredients",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("dish_id", sa.Integer(), nullable=False),
        sa.Column("recipe_ingredient_id", sa.Integer(), nullable=True),
        sa.Column("task_id", sa.String(length=255), nullable=True),
        sa.Column("st2_execution_id", sa.String(length=100), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("canceled_at", sa.DateTime(), nullable=True),
        sa.Column("result", mysql.JSON(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("deleted", sa.Boolean(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["dish_id"], ["dishes.id"]),
        sa.ForeignKeyConstraint(["recipe_ingredient_id"], ["recipe_ingredients.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_dish_ingredients_dish_id", "dish_ingredients", ["dish_id"], unique=False
    )
    op.create_index(
        "ix_dish_ingredients_task_id", "dish_ingredients", ["task_id"], unique=False
    )
    op.create_index(
        "ix_dish_ingredients_st2_execution_id",
        "dish_ingredients",
        ["st2_execution_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_dish_ingredients_st2_execution_id", table_name="dish_ingredients"
    )
    op.drop_index("ix_dish_ingredients_task_id", table_name="dish_ingredients")
    op.drop_index("ix_dish_ingredients_dish_id", table_name="dish_ingredients")
    op.drop_table("dish_ingredients")

    op.drop_index(op.f("ix_dishes_processing_status"), table_name="dishes")
    op.drop_index(op.f("ix_dishes_workflow_execution_id"), table_name="dishes")
    op.drop_index(op.f("ix_dishes_req_id"), table_name="dishes")
    op.drop_index(op.f("ix_dishes_id"), table_name="dishes")
    op.drop_table("dishes")

    op.drop_index(op.f("ix_orders_created_at"), table_name="orders")
    op.drop_index(op.f("ix_orders_instance"), table_name="orders")
    op.drop_index(op.f("ix_orders_severity"), table_name="orders")
    op.drop_index(op.f("ix_orders_alert_group_name"), table_name="orders")
    op.drop_index(op.f("ix_orders_processing_status"), table_name="orders")
    op.drop_index(op.f("ix_orders_alert_status"), table_name="orders")
    op.drop_index(op.f("ix_orders_fingerprint"), table_name="orders")
    op.drop_index(op.f("ix_orders_req_id"), table_name="orders")
    op.drop_index(op.f("ix_orders_id"), table_name="orders")
    op.drop_table("orders")

    op.drop_index("idx_recipe_ingredient_order", table_name="recipe_ingredients")
    op.drop_index(op.f("ix_recipe_ingredients_id"), table_name="recipe_ingredients")
    op.drop_table("recipe_ingredients")

    op.drop_index(op.f("ix_ingredients_task_id"), table_name="ingredients")
    op.drop_index(op.f("ix_ingredients_id"), table_name="ingredients")
    op.drop_table("ingredients")

    op.drop_index(op.f("ix_recipes_name"), table_name="recipes")
    op.drop_index(op.f("ix_recipes_id"), table_name="recipes")
    op.drop_table("recipes")
