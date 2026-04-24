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
        sa.Column("clear_timeout_sec", sa.Integer(), nullable=True),
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
        sa.Column("execution_target", sa.String(length=100), nullable=False),
        sa.Column("destination_target", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("task_key_template", sa.String(length=255), nullable=False),
        sa.Column("execution_id", sa.String(length=100), nullable=True),
        sa.Column("execution_payload", mysql.JSON(), nullable=True),
        sa.Column("execution_parameters", mysql.JSON(), nullable=True),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column(
            "execution_engine", sa.String(length=50), nullable=False, server_default="undefined"
        ),
        sa.Column(
            "execution_purpose", sa.String(length=32), nullable=False, server_default="utility"
        ),
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
    op.create_index(
        op.f("ix_ingredients_execution_target"), "ingredients", ["execution_target"], unique=False
    )
    op.create_index(
        "ux_ingredients_engine_target",
        "ingredients",
        ["execution_engine", "execution_target", "destination_target", "task_key_template"],
        unique=True,
    )

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
        sa.Column("execution_payload_override", mysql.JSON(), nullable=True),
        sa.Column("execution_parameters_override", mysql.JSON(), nullable=True),
        sa.Column("expected_duration_sec_override", sa.Integer(), nullable=True),
        sa.Column("timeout_duration_sec_override", sa.Integer(), nullable=True),
        sa.Column("run_phase", sa.String(length=16), nullable=False, server_default="both"),
        sa.Column("run_condition", sa.String(length=40), nullable=False),
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
    op.execute("""
        CREATE TABLE orders (
            id INTEGER NOT NULL AUTO_INCREMENT,
            req_id VARCHAR(100) NOT NULL,
            fingerprint VARCHAR(255) NOT NULL,
            alert_status VARCHAR(50) NOT NULL,
            processing_status VARCHAR(50) NOT NULL,
            is_active BOOLEAN NOT NULL,
            remediation_outcome VARCHAR(16) NOT NULL DEFAULT 'pending',
            clear_timeout_sec INTEGER,
            clear_deadline_at DATETIME,
            clear_timed_out_at DATETIME,
            auto_close_eligible BOOLEAN NOT NULL DEFAULT 0,
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
        """)
    op.create_index(op.f("ix_orders_id"), "orders", ["id"], unique=False)
    op.create_index(op.f("ix_orders_req_id"), "orders", ["req_id"], unique=False)
    op.create_index(op.f("ix_orders_fingerprint"), "orders", ["fingerprint"], unique=False)
    op.create_index(op.f("ix_orders_alert_status"), "orders", ["alert_status"], unique=False)
    op.create_index(
        op.f("ix_orders_processing_status"), "orders", ["processing_status"], unique=False
    )
    op.create_index(op.f("ix_orders_is_active"), "orders", ["is_active"], unique=False)
    op.create_index(
        "ix_orders_remediation_outcome",
        "orders",
        ["remediation_outcome"],
        unique=False,
    )
    op.create_index(
        "ix_orders_clear_deadline_at",
        "orders",
        ["clear_deadline_at"],
        unique=False,
    )
    op.create_index(
        "ix_orders_clear_timed_out_at",
        "orders",
        ["clear_timed_out_at"],
        unique=False,
    )
    op.create_index(
        "ix_orders_auto_close_eligible",
        "orders",
        ["auto_close_eligible"],
        unique=False,
    )

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
    op.create_index(
        op.f("ix_orders_bakery_ticket_id"), "orders", ["bakery_ticket_id"], unique=False
    )
    op.create_index(
        op.f("ix_orders_bakery_operation_id"), "orders", ["bakery_operation_id"], unique=False
    )
    op.create_index(
        op.f("ix_orders_bakery_ticket_state"), "orders", ["bakery_ticket_state"], unique=False
    )
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
        sa.Column("execution_ref", sa.String(length=100), nullable=True),
        sa.Column("order_id", sa.Integer(), nullable=True),
        sa.Column("recipe_id", sa.Integer(), nullable=False),
        sa.Column("run_phase", sa.String(length=16), nullable=False, server_default="firing"),
        sa.Column("processing_status", sa.String(length=50), nullable=False),
        sa.Column("execution_status", sa.String(length=50), nullable=True),
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
        op.f("ix_dishes_execution_ref"),
        "dishes",
        ["execution_ref"],
        unique=False,
    )
    op.create_index(
        op.f("ix_dishes_processing_status"), "dishes", ["processing_status"], unique=False
    )
    op.create_index(op.f("ix_dishes_run_phase"), "dishes", ["run_phase"], unique=False)

    # Dish Ingredients (per-task executions)
    op.create_table(
        "dish_ingredients",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("dish_id", sa.Integer(), nullable=False),
        sa.Column("recipe_ingredient_id", sa.Integer(), nullable=True),
        sa.Column("task_key", sa.String(length=255), nullable=True),
        sa.Column("execution_engine", sa.String(length=50), nullable=True),
        sa.Column("execution_target", sa.String(length=255), nullable=True),
        sa.Column("destination_target", sa.String(length=255), nullable=True),
        sa.Column("execution_ref", sa.String(length=100), nullable=True),
        sa.Column("execution_payload", mysql.JSON(), nullable=True),
        sa.Column("execution_parameters", mysql.JSON(), nullable=True),
        sa.Column("expected_duration_sec", sa.Integer(), nullable=True),
        sa.Column("timeout_duration_sec", sa.Integer(), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=True),
        sa.Column("retry_delay", sa.Integer(), nullable=True),
        sa.Column("on_failure", sa.String(length=50), nullable=True),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "execution_ref_norm",
            sa.String(length=100),
            sa.Computed("IFNULL(execution_ref, '')", persisted=True),
        ),
        sa.Column(
            "recipe_ingredient_id_norm",
            sa.Integer(),
            sa.Computed("IFNULL(recipe_ingredient_id, 0)", persisted=True),
        ),
        sa.Column(
            "task_key_norm",
            sa.String(length=255),
            sa.Computed("IFNULL(task_key, '')", persisted=True),
        ),
        sa.Column("execution_status", sa.String(length=50), nullable=True),
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
    op.create_index("ix_dish_ingredients_task_key", "dish_ingredients", ["task_key"], unique=False)
    op.create_index(
        "ix_dish_ingredients_execution_ref",
        "dish_ingredients",
        ["execution_ref"],
        unique=False,
    )
    op.create_index(
        "ix_dish_ingredients_execution_engine",
        "dish_ingredients",
        ["execution_engine"],
        unique=False,
    )
    op.create_index(
        "ux_dish_ingredients_dish_step",
        "dish_ingredients",
        ["dish_id", "recipe_ingredient_id_norm", "task_key_norm"],
        unique=True,
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
        sa.Column("reconcile_metadata", mysql.JSON(), nullable=True),
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
        "ix_order_communications_order_id",
        "order_communications",
        ["order_id"],
        unique=False,
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

    op.create_table(
        "bakery_monitor_state",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("monitor_id", sa.String(length=255), nullable=False),
        sa.Column("monitor_uuid", sa.String(length=36), nullable=True),
        sa.Column("hmac_key_id", sa.String(length=255), nullable=True),
        sa.Column("encrypted_hmac_secret", sa.Text(), nullable=True),
        sa.Column("installation_id", sa.String(length=255), nullable=True),
        sa.Column("last_route_catalog_hash", sa.String(length=64), nullable=True),
        sa.Column("route_sync_dirty", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("last_heartbeat_status", sa.String(length=64), nullable=True),
        sa.Column("last_heartbeat_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("monitor_id", name="ux_bakery_monitor_state_monitor_id"),
        sa.UniqueConstraint("monitor_uuid", name="ux_bakery_monitor_state_monitor_uuid"),
    )
    op.create_index("ix_bakery_monitor_state_id", "bakery_monitor_state", ["id"], unique=False)
    op.create_index(
        "ix_bakery_monitor_state_monitor_id",
        "bakery_monitor_state",
        ["monitor_id"],
        unique=False,
    )
    op.create_index(
        "ix_bakery_monitor_state_monitor_uuid",
        "bakery_monitor_state",
        ["monitor_uuid"],
        unique=False,
    )
    op.create_index(
        "ix_bakery_monitor_state_last_heartbeat_status",
        "bakery_monitor_state",
        ["last_heartbeat_status"],
        unique=False,
    )
    op.create_index(
        "ix_bakery_monitor_state_last_heartbeat_at",
        "bakery_monitor_state",
        ["last_heartbeat_at"],
        unique=False,
    )

    op.create_table(
        "release_update_notifications",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("oci_repository", sa.String(length=512), nullable=False),
        sa.Column("current_app_version", sa.String(length=100), nullable=False),
        sa.Column("current_chart_version", sa.String(length=100), nullable=False),
        sa.Column("available_app_version", sa.String(length=100), nullable=False),
        sa.Column("available_chart_version", sa.String(length=100), nullable=False),
        sa.Column("available_created_at", sa.DateTime(), nullable=True),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("latest_error", sa.Text(), nullable=True),
        sa.Column("detected_at", sa.DateTime(), nullable=False),
        sa.Column("notified_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "oci_repository",
            "available_app_version",
            "available_chart_version",
            name="ux_release_update_notifications_release",
        ),
    )
    op.create_index(
        "ix_release_update_notifications_id",
        "release_update_notifications",
        ["id"],
        unique=False,
    )
    op.create_index(
        "ix_release_update_notifications_oci_repository",
        "release_update_notifications",
        ["oci_repository"],
        unique=False,
    )
    op.create_index(
        "ix_release_update_notifications_available_app_version",
        "release_update_notifications",
        ["available_app_version"],
        unique=False,
    )
    op.create_index(
        "ix_release_update_notifications_available_chart_version",
        "release_update_notifications",
        ["available_chart_version"],
        unique=False,
    )
    op.create_index(
        "ix_release_update_notifications_state",
        "release_update_notifications",
        ["state"],
        unique=False,
    )

    op.create_table(
        "release_update_notification_deliveries",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("notification_id", sa.Integer(), nullable=False),
        sa.Column("route_id", sa.String(length=255), nullable=False),
        sa.Column("route_label", sa.String(length=255), nullable=False),
        sa.Column("execution_target", sa.String(length=100), nullable=False),
        sa.Column("destination_target", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("provider_config", mysql.JSON(), nullable=True),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("bakery_communication_id", sa.String(length=255), nullable=True),
        sa.Column("bakery_operation_id", sa.String(length=255), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("delivered_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["notification_id"], ["release_update_notifications.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "notification_id",
            "route_id",
            name="ux_release_update_notification_deliveries_route",
        ),
    )
    op.create_index(
        "ix_release_update_notification_deliveries_id",
        "release_update_notification_deliveries",
        ["id"],
        unique=False,
    )
    op.create_index(
        "ix_release_update_notification_deliveries_notification_id",
        "release_update_notification_deliveries",
        ["notification_id"],
        unique=False,
    )
    op.create_index(
        "ix_release_update_notification_deliveries_route_id",
        "release_update_notification_deliveries",
        ["route_id"],
        unique=False,
    )
    op.create_index(
        "ix_release_update_notification_deliveries_execution_target",
        "release_update_notification_deliveries",
        ["execution_target"],
        unique=False,
    )
    op.create_index(
        "ix_release_update_notification_deliveries_state",
        "release_update_notification_deliveries",
        ["state"],
        unique=False,
    )
    op.create_index(
        "ix_release_update_notification_deliveries_bakery_communication_id",
        "release_update_notification_deliveries",
        ["bakery_communication_id"],
        unique=False,
    )
    op.create_index(
        "ix_release_update_notification_deliveries_bakery_operation_id",
        "release_update_notification_deliveries",
        ["bakery_operation_id"],
        unique=False,
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
    op.create_index(
        "ix_alert_suppressions_ends_at", "alert_suppressions", ["ends_at"], unique=False
    )
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

    op.create_table(
        "auth_principals",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("subject_id", sa.String(length=255), nullable=False),
        sa.Column("username", sa.String(length=255), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=True),
        sa.Column("principal_type", sa.String(length=16), nullable=False),
        sa.Column("groups_json", mysql.JSON(), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "provider",
            "subject_id",
            name="ux_auth_principals_provider_subject",
        ),
    )
    op.create_index("ix_auth_principals_id", "auth_principals", ["id"], unique=False)
    op.create_index(
        "ix_auth_principals_provider",
        "auth_principals",
        ["provider"],
        unique=False,
    )
    op.create_index(
        "ix_auth_principals_username",
        "auth_principals",
        ["username"],
        unique=False,
    )
    op.create_index(
        "ix_auth_principals_provider_username",
        "auth_principals",
        ["provider", "username"],
        unique=False,
    )

    op.create_table(
        "auth_role_bindings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("binding_type", sa.String(length=16), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("principal_id", sa.Integer(), nullable=True),
        sa.Column("external_group", sa.String(length=255), nullable=True),
        sa.Column("created_by", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["principal_id"], ["auth_principals.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "provider",
            "binding_type",
            "principal_id",
            name="ux_auth_role_bindings_provider_type_principal",
        ),
        sa.UniqueConstraint(
            "provider",
            "binding_type",
            "external_group",
            name="ux_auth_role_bindings_provider_type_group",
        ),
    )
    op.create_index("ix_auth_role_bindings_id", "auth_role_bindings", ["id"], unique=False)
    op.create_index(
        "ix_auth_role_bindings_provider",
        "auth_role_bindings",
        ["provider"],
        unique=False,
    )
    op.create_index(
        "ix_auth_role_bindings_binding_type",
        "auth_role_bindings",
        ["binding_type"],
        unique=False,
    )
    op.create_index(
        "ix_auth_role_bindings_role",
        "auth_role_bindings",
        ["role"],
        unique=False,
    )
    op.create_index(
        "ix_auth_role_bindings_principal_id",
        "auth_role_bindings",
        ["principal_id"],
        unique=False,
    )
    op.create_index(
        "ix_auth_role_bindings_external_group",
        "auth_role_bindings",
        ["external_group"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_release_update_notification_deliveries_bakery_operation_id",
        table_name="release_update_notification_deliveries",
    )
    op.drop_index(
        "ix_release_update_notification_deliveries_bakery_communication_id",
        table_name="release_update_notification_deliveries",
    )
    op.drop_index(
        "ix_release_update_notification_deliveries_state",
        table_name="release_update_notification_deliveries",
    )
    op.drop_index(
        "ix_release_update_notification_deliveries_execution_target",
        table_name="release_update_notification_deliveries",
    )
    op.drop_index(
        "ix_release_update_notification_deliveries_route_id",
        table_name="release_update_notification_deliveries",
    )
    op.drop_index(
        "ix_release_update_notification_deliveries_notification_id",
        table_name="release_update_notification_deliveries",
    )
    op.drop_index(
        "ix_release_update_notification_deliveries_id",
        table_name="release_update_notification_deliveries",
    )
    op.drop_table("release_update_notification_deliveries")

    op.drop_index(
        "ix_release_update_notifications_state",
        table_name="release_update_notifications",
    )
    op.drop_index(
        "ix_release_update_notifications_available_chart_version",
        table_name="release_update_notifications",
    )
    op.drop_index(
        "ix_release_update_notifications_available_app_version",
        table_name="release_update_notifications",
    )
    op.drop_index(
        "ix_release_update_notifications_oci_repository",
        table_name="release_update_notifications",
    )
    op.drop_index("ix_release_update_notifications_id", table_name="release_update_notifications")
    op.drop_table("release_update_notifications")

    op.drop_index(
        "ix_bakery_monitor_state_last_heartbeat_at",
        table_name="bakery_monitor_state",
    )
    op.drop_index(
        "ix_bakery_monitor_state_last_heartbeat_status",
        table_name="bakery_monitor_state",
    )
    op.drop_index(
        "ix_bakery_monitor_state_monitor_uuid",
        table_name="bakery_monitor_state",
    )
    op.drop_index(
        "ix_bakery_monitor_state_monitor_id",
        table_name="bakery_monitor_state",
    )
    op.drop_index("ix_bakery_monitor_state_id", table_name="bakery_monitor_state")
    op.drop_table("bakery_monitor_state")

    op.drop_index("ix_auth_role_bindings_external_group", table_name="auth_role_bindings")
    op.drop_index("ix_auth_role_bindings_principal_id", table_name="auth_role_bindings")
    op.drop_index("ix_auth_role_bindings_role", table_name="auth_role_bindings")
    op.drop_index("ix_auth_role_bindings_binding_type", table_name="auth_role_bindings")
    op.drop_index("ix_auth_role_bindings_provider", table_name="auth_role_bindings")
    op.drop_index("ix_auth_role_bindings_id", table_name="auth_role_bindings")
    op.drop_table("auth_role_bindings")

    op.drop_index("ix_auth_principals_provider_username", table_name="auth_principals")
    op.drop_index("ix_auth_principals_username", table_name="auth_principals")
    op.drop_index("ix_auth_principals_provider", table_name="auth_principals")
    op.drop_index("ix_auth_principals_id", table_name="auth_principals")
    op.drop_table("auth_principals")

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

    op.drop_index("ux_dish_ingredients_dish_step", table_name="dish_ingredients")
    op.drop_index("ix_dish_ingredients_execution_engine", table_name="dish_ingredients")
    op.drop_index("ix_dish_ingredients_execution_ref", table_name="dish_ingredients")
    op.drop_index("ix_dish_ingredients_task_key", table_name="dish_ingredients")
    op.drop_index("ix_dish_ingredients_dish_id", table_name="dish_ingredients")
    op.drop_table("dish_ingredients")

    op.drop_index("ix_order_communications_remote_state", table_name="order_communications")
    op.drop_index("ix_order_communications_bakery_operation_id", table_name="order_communications")
    op.drop_index("ix_order_communications_bakery_ticket_id", table_name="order_communications")
    op.drop_index("ix_order_communications_execution_target", table_name="order_communications")
    op.drop_index("ix_order_communications_order_id", table_name="order_communications")
    op.drop_index("ix_order_communications_id", table_name="order_communications")
    op.drop_table("order_communications")

    op.drop_index(op.f("ix_dishes_run_phase"), table_name="dishes")
    op.drop_index(op.f("ix_dishes_processing_status"), table_name="dishes")
    op.drop_index(op.f("ix_dishes_execution_ref"), table_name="dishes")
    op.drop_index(op.f("ix_dishes_req_id"), table_name="dishes")
    op.drop_index(op.f("ix_dishes_id"), table_name="dishes")
    op.drop_table("dishes")

    op.drop_index("ix_orders_auto_close_eligible", table_name="orders")
    op.drop_index("ix_orders_clear_timed_out_at", table_name="orders")
    op.drop_index("ix_orders_clear_deadline_at", table_name="orders")
    op.drop_index("ix_orders_remediation_outcome", table_name="orders")
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

    op.drop_index("ux_ingredients_engine_target", table_name="ingredients")
    op.drop_index(op.f("ix_ingredients_execution_target"), table_name="ingredients")
    op.drop_index(op.f("ix_ingredients_id"), table_name="ingredients")
    op.drop_table("ingredients")

    op.drop_index(op.f("ix_recipes_name"), table_name="recipes")
    op.drop_index(op.f("ix_recipes_id"), table_name="recipes")
    op.drop_table("recipes")
