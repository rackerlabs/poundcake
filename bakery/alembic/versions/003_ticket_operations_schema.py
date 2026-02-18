"""Add new ticket + operation cutover schema.

Revision ID: 003
Revises: 002
Create Date: 2026-02-18 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

# revision identifiers, used by Alembic.
revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create tables for logical tickets and async operations."""
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
        "ix_tickets_internal_ticket_id", "tickets", ["internal_ticket_id"], unique=False
    )
    op.create_index("ix_tickets_provider_type", "tickets", ["provider_type"], unique=False)
    op.create_index(
        "ix_tickets_provider_ticket_id", "tickets", ["provider_ticket_id"], unique=False
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
        "ix_ticket_operations_operation_id", "ticket_operations", ["operation_id"], unique=False
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
        "ix_idempotency_keys_idempotency_key", "idempotency_keys", ["idempotency_key"], unique=False
    )
    op.create_index("ix_idempotency_keys_action", "idempotency_keys", ["action"], unique=False)
    op.create_index(
        "ix_idempotency_keys_ticket_scope", "idempotency_keys", ["ticket_scope"], unique=False
    )
    op.create_index(
        "ix_idempotency_keys_operation_id", "idempotency_keys", ["operation_id"], unique=False
    )


def downgrade() -> None:
    """Drop cutover tables."""
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
