#  ___                        _  ____      _
# |  _ \ ___  _   _ _ __   __| |/ ___|__ _| | _____
# | |_) / _ \| | | | '_ \ / _` | |   / _` | |/ / _ \
# |  __/ (_) | |_| | | | | (_| | |__| (_| |   <  __/
# |_|   \___/ \__,_|_| |_|\__,_|\____\__,_|_|\_\___|
#
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
        sa.Column("source_type", sa.String(length=50), nullable=False, server_default="undefined"),
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
        sa.Column("source_type", sa.String(length=50), nullable=False, server_default="undefined"),
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
    op.create_index(op.f("ix_ingredients_task_id"), "ingredients", ["task_id"], unique=True)

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
        sa.Column("input_parameters", mysql.JSON(), nullable=True),
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
    # Note: We need to use raw SQL to create the table with the generated column
    # because SQLAlchemy doesn't support GENERATED columns in create_table()
    op.execute(
        """
        CREATE TABLE orders (
            id INTEGER NOT NULL AUTO_INCREMENT,
            req_id VARCHAR(100) NOT NULL,
            fingerprint VARCHAR(255) NOT NULL,
            alert_status VARCHAR(50) NOT NULL,
            processing_status VARCHAR(50) NOT NULL,
            is_active BOOLEAN NOT NULL,
            alert_group_name VARCHAR(255) NOT NULL,
            severity VARCHAR(50),
            instance VARCHAR(255),
            counter INTEGER NOT NULL,
            bakery_ticket_id VARCHAR(36),
            bakery_operation_id VARCHAR(36),
            bakery_ticket_state VARCHAR(32),
            bakery_permanent_failure BOOLEAN NOT NULL DEFAULT 0,
            bakery_last_error TEXT,
            labels JSON NOT NULL,
            annotations JSON,
            raw_data JSON,
            starts_at DATETIME NOT NULL,
            ends_at DATETIME,
            created_at DATETIME NOT NULL,
            updated_at DATETIME NOT NULL,
            bakery_comms_id VARCHAR(36),
            fingerprint_when_active VARCHAR(255) GENERATED ALWAYS AS (IF(is_active = 1, fingerprint, NULL)) STORED,
            PRIMARY KEY (id)
        )
        """
    )
    op.create_index(op.f("ix_orders_id"), "orders", ["id"], unique=False)
    op.create_index(op.f("ix_orders_req_id"), "orders", ["req_id"], unique=False)
    op.create_index(op.f("ix_orders_fingerprint"), "orders", ["fingerprint"], unique=False)
    op.create_index(op.f("ix_orders_alert_status"), "orders", ["alert_status"], unique=False)
    op.create_index(
        op.f("ix_orders_processing_status"), "orders", ["processing_status"], unique=False
    )
    op.create_index(op.f("ix_orders_is_active"), "orders", ["is_active"], unique=False)

    # Create unique index on the generated column
    # Since it's NULL for inactive orders, multiple inactive orders can have the same fingerprint
    # But only one active order per fingerprint is allowed
    op.create_index(
        "ux_orders_fingerprint_active", "orders", ["fingerprint_when_active"], unique=True
    )
    op.create_index(
        op.f("ix_orders_alert_group_name"), "orders", ["alert_group_name"], unique=False
    )
    op.create_index(op.f("ix_orders_severity"), "orders", ["severity"], unique=False)
    op.create_index(op.f("ix_orders_instance"), "orders", ["instance"], unique=False)
    op.create_index(op.f("ix_orders_created_at"), "orders", ["created_at"], unique=False)
    op.create_index(op.f("ix_orders_bakery_ticket_id"), "orders", ["bakery_ticket_id"], unique=False)
    op.create_index(
        op.f("ix_orders_bakery_operation_id"), "orders", ["bakery_operation_id"], unique=False
    )
    op.create_index(op.f("ix_orders_bakery_ticket_state"), "orders", ["bakery_ticket_state"], unique=False)
    op.create_index(
        op.f("ix_orders_bakery_permanent_failure"),
        "orders",
        ["bakery_permanent_failure"],
        unique=False,
    )

    # Dishes
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
        sa.Column(
            "task_id_norm",
            sa.String(length=255),
            sa.Computed("IFNULL(task_id, '')", persisted=True),
        ),
        sa.Column(
            "st2_execution_id_norm",
            sa.String(length=100),
            sa.Computed("IFNULL(st2_execution_id, '')", persisted=True),
        ),
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
    op.create_index("ix_dish_ingredients_dish_id", "dish_ingredients", ["dish_id"], unique=False)
    op.create_index("ix_dish_ingredients_task_id", "dish_ingredients", ["task_id"], unique=False)
    op.create_index(
        "ix_dish_ingredients_st2_execution_id",
        "dish_ingredients",
        ["st2_execution_id"],
        unique=False,
    )
    op.create_index(
        "ux_dish_ingredients_dish_task_exec",
        "dish_ingredients",
        ["dish_id", "task_id_norm", "st2_execution_id_norm"],
        unique=True,
    )

    # Alert suppressions
    op.create_table(
        "alert_suppressions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("scope", sa.String(length=32), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("starts_at", sa.DateTime(), nullable=False),
        sa.Column("ends_at", sa.DateTime(), nullable=False),
        sa.Column("canceled_at", sa.DateTime(), nullable=True),
        sa.Column("created_by", sa.String(length=255), nullable=True),
        sa.Column("summary_ticket_enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_alert_suppressions_id", "alert_suppressions", ["id"], unique=False)
    op.create_index("ix_alert_suppressions_name", "alert_suppressions", ["name"], unique=False)
    op.create_index(
        "ix_alert_suppressions_starts_at",
        "alert_suppressions",
        ["starts_at"],
        unique=False,
    )
    op.create_index("ix_alert_suppressions_ends_at", "alert_suppressions", ["ends_at"], unique=False)
    op.create_index(
        "ix_alert_suppressions_canceled_at",
        "alert_suppressions",
        ["canceled_at"],
        unique=False,
    )
    op.create_index(
        "idx_alert_suppressions_active_lookup",
        "alert_suppressions",
        ["enabled", "starts_at", "ends_at", "canceled_at"],
        unique=False,
    )

    op.create_table(
        "alert_suppression_matchers",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("suppression_id", sa.Integer(), nullable=False),
        sa.Column("label_key", sa.String(length=255), nullable=False),
        sa.Column("operator", sa.String(length=32), nullable=False),
        sa.Column("value", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["suppression_id"], ["alert_suppressions.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_alert_suppression_matchers_id",
        "alert_suppression_matchers",
        ["id"],
        unique=False,
    )
    op.create_index(
        "ix_alert_suppression_matchers_suppression_id",
        "alert_suppression_matchers",
        ["suppression_id"],
        unique=False,
    )

    op.create_table(
        "suppressed_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("suppression_id", sa.Integer(), nullable=False),
        sa.Column("received_at", sa.DateTime(), nullable=False),
        sa.Column("fingerprint", sa.String(length=255), nullable=True),
        sa.Column("alertname", sa.String(length=255), nullable=True),
        sa.Column("severity", sa.String(length=64), nullable=True),
        sa.Column("labels_json", mysql.JSON(), nullable=False),
        sa.Column("annotations_json", mysql.JSON(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=True),
        sa.Column("req_id", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["suppression_id"], ["alert_suppressions.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_suppressed_events_id", "suppressed_events", ["id"], unique=False)
    op.create_index(
        "ix_suppressed_events_suppression_id",
        "suppressed_events",
        ["suppression_id"],
        unique=False,
    )
    op.create_index(
        "ix_suppressed_events_received_at",
        "suppressed_events",
        ["received_at"],
        unique=False,
    )
    op.create_index(
        "ix_suppressed_events_fingerprint",
        "suppressed_events",
        ["fingerprint"],
        unique=False,
    )
    op.create_index(
        "ix_suppressed_events_alertname",
        "suppressed_events",
        ["alertname"],
        unique=False,
    )
    op.create_index(
        "ix_suppressed_events_severity",
        "suppressed_events",
        ["severity"],
        unique=False,
    )
    op.create_index(
        "ix_suppressed_events_payload_hash",
        "suppressed_events",
        ["payload_hash"],
        unique=False,
    )
    op.create_index("ix_suppressed_events_req_id", "suppressed_events", ["req_id"], unique=False)
    op.create_index(
        "idx_suppressed_events_suppression_received_at",
        "suppressed_events",
        ["suppression_id", "received_at"],
        unique=False,
    )
    op.create_index(
        "idx_suppressed_events_fingerprint",
        "suppressed_events",
        ["fingerprint"],
        unique=False,
    )

    op.create_table(
        "suppression_summaries",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("suppression_id", sa.Integer(), nullable=False),
        sa.Column("total_suppressed", sa.Integer(), nullable=False),
        sa.Column("total_cleared", sa.Integer(), nullable=False),
        sa.Column("total_still_firing", sa.Integer(), nullable=False),
        sa.Column("by_alertname_json", mysql.JSON(), nullable=True),
        sa.Column("by_severity_json", mysql.JSON(), nullable=True),
        sa.Column("still_firing_alerts_json", mysql.JSON(), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(), nullable=True),
        sa.Column("summary_created_at", sa.DateTime(), nullable=True),
        sa.Column("bakery_ticket_id", sa.String(length=36), nullable=True),
        sa.Column("bakery_create_operation_id", sa.String(length=36), nullable=True),
        sa.Column("bakery_close_operation_id", sa.String(length=36), nullable=True),
        sa.Column("summary_close_at", sa.DateTime(), nullable=True),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["suppression_id"], ["alert_suppressions.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("suppression_id"),
    )
    op.create_index("ix_suppression_summaries_id", "suppression_summaries", ["id"], unique=False)
    op.create_index(
        "ix_suppression_summaries_suppression_id",
        "suppression_summaries",
        ["suppression_id"],
        unique=True,
    )
    op.create_index(
        "ix_suppression_summaries_bakery_ticket_id",
        "suppression_summaries",
        ["bakery_ticket_id"],
        unique=False,
    )
    op.create_index(
        "ix_suppression_summaries_bakery_create_operation_id",
        "suppression_summaries",
        ["bakery_create_operation_id"],
        unique=False,
    )
    op.create_index(
        "ix_suppression_summaries_bakery_close_operation_id",
        "suppression_summaries",
        ["bakery_close_operation_id"],
        unique=False,
    )
    op.create_index(
        "ix_suppression_summaries_state",
        "suppression_summaries",
        ["state"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_suppression_summaries_state", table_name="suppression_summaries")
    op.drop_index(
        "ix_suppression_summaries_bakery_close_operation_id",
        table_name="suppression_summaries",
    )
    op.drop_index(
        "ix_suppression_summaries_bakery_create_operation_id",
        table_name="suppression_summaries",
    )
    op.drop_index("ix_suppression_summaries_bakery_ticket_id", table_name="suppression_summaries")
    op.drop_index("ix_suppression_summaries_suppression_id", table_name="suppression_summaries")
    op.drop_index("ix_suppression_summaries_id", table_name="suppression_summaries")
    op.drop_table("suppression_summaries")

    op.drop_index("idx_suppressed_events_fingerprint", table_name="suppressed_events")
    op.drop_index(
        "idx_suppressed_events_suppression_received_at",
        table_name="suppressed_events",
    )
    op.drop_index("ix_suppressed_events_req_id", table_name="suppressed_events")
    op.drop_index("ix_suppressed_events_payload_hash", table_name="suppressed_events")
    op.drop_index("ix_suppressed_events_severity", table_name="suppressed_events")
    op.drop_index("ix_suppressed_events_alertname", table_name="suppressed_events")
    op.drop_index("ix_suppressed_events_fingerprint", table_name="suppressed_events")
    op.drop_index("ix_suppressed_events_received_at", table_name="suppressed_events")
    op.drop_index("ix_suppressed_events_suppression_id", table_name="suppressed_events")
    op.drop_index("ix_suppressed_events_id", table_name="suppressed_events")
    op.drop_table("suppressed_events")

    op.drop_index(
        "ix_alert_suppression_matchers_suppression_id",
        table_name="alert_suppression_matchers",
    )
    op.drop_index("ix_alert_suppression_matchers_id", table_name="alert_suppression_matchers")
    op.drop_table("alert_suppression_matchers")

    op.drop_index("idx_alert_suppressions_active_lookup", table_name="alert_suppressions")
    op.drop_index("ix_alert_suppressions_canceled_at", table_name="alert_suppressions")
    op.drop_index("ix_alert_suppressions_ends_at", table_name="alert_suppressions")
    op.drop_index("ix_alert_suppressions_starts_at", table_name="alert_suppressions")
    op.drop_index("ix_alert_suppressions_name", table_name="alert_suppressions")
    op.drop_index("ix_alert_suppressions_id", table_name="alert_suppressions")
    op.drop_table("alert_suppressions")

    op.drop_index("ux_dish_ingredients_dish_task_exec", table_name="dish_ingredients")
    op.drop_index("ix_dish_ingredients_st2_execution_id", table_name="dish_ingredients")
    op.drop_index("ix_dish_ingredients_task_id", table_name="dish_ingredients")
    op.drop_index("ix_dish_ingredients_dish_id", table_name="dish_ingredients")
    op.drop_table("dish_ingredients")

    op.drop_index(op.f("ix_dishes_processing_status"), table_name="dishes")
    op.drop_index(op.f("ix_dishes_workflow_execution_id"), table_name="dishes")
    op.drop_index(op.f("ix_dishes_req_id"), table_name="dishes")
    op.drop_index(op.f("ix_dishes_id"), table_name="dishes")
    op.drop_table("dishes")

    op.drop_index(op.f("ix_orders_bakery_permanent_failure"), table_name="orders")
    op.drop_index(op.f("ix_orders_bakery_ticket_state"), table_name="orders")
    op.drop_index(op.f("ix_orders_bakery_operation_id"), table_name="orders")
    op.drop_index(op.f("ix_orders_bakery_ticket_id"), table_name="orders")
    op.drop_column("orders", "bakery_last_error")
    op.drop_column("orders", "bakery_permanent_failure")
    op.drop_column("orders", "bakery_ticket_state")
    op.drop_column("orders", "bakery_operation_id")
    op.drop_column("orders", "bakery_ticket_id")

    op.drop_index(op.f("ix_orders_created_at"), table_name="orders")
    op.drop_index(op.f("ix_orders_instance"), table_name="orders")
    op.drop_index(op.f("ix_orders_severity"), table_name="orders")
    op.drop_index(op.f("ix_orders_alert_group_name"), table_name="orders")
    op.drop_index("ux_orders_fingerprint_active", table_name="orders")
    op.drop_index(op.f("ix_orders_is_active"), table_name="orders")
    op.drop_index(op.f("ix_orders_processing_status"), table_name="orders")
    op.drop_index(op.f("ix_orders_alert_status"), table_name="orders")
    op.drop_index(op.f("ix_orders_fingerprint"), table_name="orders")
    op.drop_index(op.f("ix_orders_req_id"), table_name="orders")
    op.drop_index(op.f("ix_orders_id"), table_name="orders")
    # Drop the generated column
    op.execute("ALTER TABLE orders DROP COLUMN fingerprint_when_active")
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
