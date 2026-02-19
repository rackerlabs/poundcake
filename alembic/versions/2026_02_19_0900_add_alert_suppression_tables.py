"""Add alert suppression tables.

Revision ID: 2026_02_19_0900
Revises: 2026_02_18_1700
Create Date: 2026-02-19 09:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

# revision identifiers, used by Alembic.
revision: str = "2026_02_19_0900"
down_revision: Union[str, None] = "2026_02_18_1700"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_names() -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return set(inspector.get_table_names())


def upgrade() -> None:
    tables = _table_names()

    if "alert_suppressions" not in tables:
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
        op.create_index(
            "ix_alert_suppressions_name",
            "alert_suppressions",
            ["name"],
            unique=False,
        )
        op.create_index(
            "ix_alert_suppressions_starts_at",
            "alert_suppressions",
            ["starts_at"],
            unique=False,
        )
        op.create_index(
            "ix_alert_suppressions_ends_at",
            "alert_suppressions",
            ["ends_at"],
            unique=False,
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

    if "alert_suppression_matchers" not in tables:
        op.create_table(
            "alert_suppression_matchers",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("suppression_id", sa.Integer(), nullable=False),
            sa.Column("label_key", sa.String(length=255), nullable=False),
            sa.Column("operator", sa.String(length=32), nullable=False),
            sa.Column("value", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(
                ["suppression_id"],
                ["alert_suppressions.id"],
            ),
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

    if "suppressed_events" not in tables:
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

    if "suppression_summaries" not in tables:
        op.create_table(
            "suppression_summaries",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("suppression_id", sa.Integer(), nullable=False),
            sa.Column("total_suppressed", sa.Integer(), nullable=False),
            sa.Column("by_alertname_json", mysql.JSON(), nullable=True),
            sa.Column("by_severity_json", mysql.JSON(), nullable=True),
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
    tables = _table_names()

    if "suppression_summaries" in tables:
        op.drop_table("suppression_summaries")
    if "suppressed_events" in tables:
        op.drop_table("suppressed_events")
    if "alert_suppression_matchers" in tables:
        op.drop_table("alert_suppression_matchers")
    if "alert_suppressions" in tables:
        op.drop_table("alert_suppressions")
