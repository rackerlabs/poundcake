"""Add ticket ID mapping table

Revision ID: 002
Revises: 001
Create Date: 2026-02-16 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create ticket_id_mappings table."""
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


def downgrade() -> None:
    """Drop ticket_id_mappings table."""
    op.drop_index("ix_ticket_id_mappings_external_ticket_id", table_name="ticket_id_mappings")
    op.drop_index("ix_ticket_id_mappings_mixer_type", table_name="ticket_id_mappings")
    op.drop_index("ix_ticket_id_mappings_internal_ticket_id", table_name="ticket_id_mappings")
    op.drop_index("ix_ticket_id_mappings_id", table_name="ticket_id_mappings")
    op.drop_table("ticket_id_mappings")
