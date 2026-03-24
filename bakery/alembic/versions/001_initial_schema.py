"""Initial schema

Revision ID: 001
Revises:
Create Date: 2024-01-01 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

# revision identifiers, used by Alembic.
revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create initial tables."""
    # Create messages table
    op.create_table(
        "messages",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("correlation_id", sa.String(length=255), nullable=False),
        sa.Column("ticket_id", sa.String(length=255), nullable=True),
        sa.Column("mixer_type", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("response_data", mysql.JSON(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("retrieved_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.Index("ix_messages_correlation_id", "correlation_id"),
        sa.Index("ix_messages_id", "id"),
        sa.Index("ix_messages_ticket_id", "ticket_id"),
        mysql_comment="Message queue for responses from ticketing systems",
    )

    # Create ticket_requests table
    op.create_table(
        "ticket_requests",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("correlation_id", sa.String(length=255), nullable=False),
        sa.Column("mixer_type", sa.String(length=50), nullable=False),
        sa.Column("action", sa.String(length=50), nullable=False),
        sa.Column("request_data", mysql.JSON(), nullable=False),
        sa.Column("ticket_id", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.Index("ix_ticket_requests_correlation_id", "correlation_id"),
        sa.Index("ix_ticket_requests_created_at", "created_at"),
        sa.Index("ix_ticket_requests_id", "id"),
        mysql_comment="Log of all ticket requests processed by Bakery",
    )

    # Create mixer_configs table
    op.create_table(
        "mixer_configs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("mixer_type", sa.String(length=50), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("config_data", mysql.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("mixer_type"),
        sa.Index("ix_mixer_configs_id", "id"),
        mysql_comment="Mixer-specific configuration",
    )

    op.create_table(
        "ticket_id_mappings",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("internal_ticket_id", sa.String(length=36), nullable=False),
        sa.Column("mixer_type", sa.String(length=50), nullable=False),
        sa.Column("external_ticket_id", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "internal_ticket_id",
            name="uq_ticket_id_mappings_internal_ticket_id",
        ),
    )
    op.create_index("ix_ticket_id_mappings_id", "ticket_id_mappings", ["id"], unique=False)
    op.create_index(
        "ix_ticket_id_mappings_internal_ticket_id",
        "ticket_id_mappings",
        ["internal_ticket_id"],
        unique=False,
    )
    op.create_index(
        "ix_ticket_id_mappings_mixer_type",
        "ticket_id_mappings",
        ["mixer_type"],
        unique=False,
    )
    op.create_index(
        "ix_ticket_id_mappings_external_ticket_id",
        "ticket_id_mappings",
        ["external_ticket_id"],
        unique=False,
    )

    op.create_table(
        "tickets",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("internal_ticket_id", sa.String(length=36), nullable=False),
        sa.Column("provider_type", sa.String(length=50), nullable=False),
        sa.Column("provider_ticket_id", sa.String(length=255), nullable=True),
        sa.Column("state", sa.String(length=50), nullable=False),
        sa.Column("latest_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("internal_ticket_id", name="uq_tickets_internal_ticket_id"),
    )
    op.create_index("ix_tickets_id", "tickets", ["id"], unique=False)
    op.create_index(
        "ix_tickets_internal_ticket_id",
        "tickets",
        ["internal_ticket_id"],
        unique=False,
    )
    op.create_index("ix_tickets_provider_type", "tickets", ["provider_type"], unique=False)
    op.create_index(
        "ix_tickets_provider_ticket_id",
        "tickets",
        ["provider_ticket_id"],
        unique=False,
    )
    op.create_index("ix_tickets_state", "tickets", ["state"], unique=False)

    op.create_table(
        "ticket_operations",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("operation_id", sa.String(length=36), nullable=False),
        sa.Column("internal_ticket_id", sa.String(length=36), nullable=False),
        sa.Column("action", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("request_payload", mysql.JSON(), nullable=False),
        sa.Column("normalized_payload", mysql.JSON(), nullable=True),
        sa.Column("provider_response", mysql.JSON(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["internal_ticket_id"], ["tickets.internal_ticket_id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("operation_id", name="uq_ticket_operations_operation_id"),
    )
    op.create_index("ix_ticket_operations_id", "ticket_operations", ["id"], unique=False)
    op.create_index(
        "ix_ticket_operations_operation_id",
        "ticket_operations",
        ["operation_id"],
        unique=False,
    )
    op.create_index(
        "ix_ticket_operations_internal_ticket_id",
        "ticket_operations",
        ["internal_ticket_id"],
        unique=False,
    )
    op.create_index("ix_ticket_operations_action", "ticket_operations", ["action"], unique=False)
    op.create_index("ix_ticket_operations_status", "ticket_operations", ["status"], unique=False)
    op.create_index(
        "ix_ticket_operations_next_attempt_at",
        "ticket_operations",
        ["next_attempt_at"],
        unique=False,
    )

    op.create_table(
        "idempotency_keys",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("action", sa.String(length=50), nullable=False),
        sa.Column("ticket_scope", sa.String(length=64), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("operation_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "idempotency_key",
            "action",
            "ticket_scope",
            name="uq_idempotency_keys_key_action_scope",
        ),
    )
    op.create_index("ix_idempotency_keys_id", "idempotency_keys", ["id"], unique=False)
    op.create_index(
        "ix_idempotency_keys_idempotency_key",
        "idempotency_keys",
        ["idempotency_key"],
        unique=False,
    )
    op.create_index("ix_idempotency_keys_action", "idempotency_keys", ["action"], unique=False)
    op.create_index(
        "ix_idempotency_keys_ticket_scope",
        "idempotency_keys",
        ["ticket_scope"],
        unique=False,
    )
    op.create_index(
        "ix_idempotency_keys_operation_id",
        "idempotency_keys",
        ["operation_id"],
        unique=False,
    )


def downgrade() -> None:
    """Drop all tables."""
    op.drop_index("ix_idempotency_keys_operation_id", table_name="idempotency_keys")
    op.drop_index("ix_idempotency_keys_ticket_scope", table_name="idempotency_keys")
    op.drop_index("ix_idempotency_keys_action", table_name="idempotency_keys")
    op.drop_index("ix_idempotency_keys_idempotency_key", table_name="idempotency_keys")
    op.drop_index("ix_idempotency_keys_id", table_name="idempotency_keys")
    op.drop_table("idempotency_keys")

    op.drop_index("ix_ticket_operations_next_attempt_at", table_name="ticket_operations")
    op.drop_index("ix_ticket_operations_status", table_name="ticket_operations")
    op.drop_index("ix_ticket_operations_action", table_name="ticket_operations")
    op.drop_index("ix_ticket_operations_internal_ticket_id", table_name="ticket_operations")
    op.drop_index("ix_ticket_operations_operation_id", table_name="ticket_operations")
    op.drop_index("ix_ticket_operations_id", table_name="ticket_operations")
    op.drop_table("ticket_operations")

    op.drop_index("ix_tickets_state", table_name="tickets")
    op.drop_index("ix_tickets_provider_ticket_id", table_name="tickets")
    op.drop_index("ix_tickets_provider_type", table_name="tickets")
    op.drop_index("ix_tickets_internal_ticket_id", table_name="tickets")
    op.drop_index("ix_tickets_id", table_name="tickets")
    op.drop_table("tickets")

    op.drop_index("ix_ticket_id_mappings_external_ticket_id", table_name="ticket_id_mappings")
    op.drop_index("ix_ticket_id_mappings_mixer_type", table_name="ticket_id_mappings")
    op.drop_index("ix_ticket_id_mappings_internal_ticket_id", table_name="ticket_id_mappings")
    op.drop_index("ix_ticket_id_mappings_id", table_name="ticket_id_mappings")
    op.drop_table("ticket_id_mappings")

    op.drop_table("mixer_configs")
    op.drop_table("ticket_requests")
    op.drop_table("messages")
