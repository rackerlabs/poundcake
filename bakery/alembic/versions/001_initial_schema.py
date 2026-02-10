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


def downgrade() -> None:
    """Drop all tables."""
    op.drop_table("mixer_configs")
    op.drop_table("ticket_requests")
    op.drop_table("messages")
