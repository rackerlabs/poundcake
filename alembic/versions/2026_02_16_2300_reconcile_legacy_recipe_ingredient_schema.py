"""Reconcile legacy recipe/ingredient schema with SQLAlchemy models.

Revision ID: 2026_02_16_2300
Revises: 2026_02_03_1600
Create Date: 2026-02-16 23:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

# revision identifiers, used by Alembic.
revision: str = "2026_02_16_2300"
down_revision: Union[str, None] = "2026_02_03_1600"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(table_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return table_name in inspector.get_table_names()


def _column_names(table_name: str) -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return {col["name"] for col in inspector.get_columns(table_name)}


def _add_column_if_missing(table_name: str, column: sa.Column) -> None:
    if column.name not in _column_names(table_name):
        op.add_column(table_name, column)


def _drop_fk_constraints_for_column(table_name: str, column_name: str) -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    for fk in inspector.get_foreign_keys(table_name):
        constrained = fk.get("constrained_columns", []) or []
        fk_name = fk.get("name")
        if fk_name and column_name in constrained:
            op.drop_constraint(fk_name, table_name, type_="foreignkey")


def _drop_indexes_for_column(table_name: str, column_name: str) -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    for idx in inspector.get_indexes(table_name):
        idx_name = idx.get("name")
        idx_columns = idx.get("column_names", []) or []
        if idx_name and column_name in idx_columns:
            op.drop_index(idx_name, table_name=table_name)


def upgrade() -> None:
    if _has_table("recipes"):
        recipe_cols = _column_names("recipes")
        if "source_type" not in recipe_cols:
            op.add_column(
                "recipes",
                sa.Column(
                    "source_type", sa.String(length=50), nullable=True, server_default="manual"
                ),
            )
        _add_column_if_missing(
            "recipes",
            sa.Column("workflow_id", sa.String(length=255), nullable=True),
        )
        _add_column_if_missing(
            "recipes",
            sa.Column("workflow_payload", mysql.JSON(), nullable=True),
        )
        _add_column_if_missing(
            "recipes",
            sa.Column("workflow_parameters", mysql.JSON(), nullable=True),
        )
        _add_column_if_missing(
            "recipes",
            sa.Column("deleted", sa.Boolean(), nullable=True, server_default=sa.text("0")),
        )
        _add_column_if_missing("recipes", sa.Column("deleted_at", sa.DateTime(), nullable=True))

        op.execute("UPDATE recipes SET source_type='manual' WHERE source_type IS NULL")
        op.execute("UPDATE recipes SET deleted=0 WHERE deleted IS NULL")
        op.alter_column(
            "recipes",
            "source_type",
            existing_type=sa.String(length=50),
            nullable=False,
            existing_nullable=True,
        )

    if _has_table("ingredients"):
        ingredient_cols = _column_names("ingredients")
        legacy_shape = "recipe_id" in ingredient_cols and "st2_action" in ingredient_cols

        _add_column_if_missing(
            "ingredients",
            sa.Column("source_type", sa.String(length=50), nullable=True, server_default="manual"),
        )
        _add_column_if_missing(
            "ingredients", sa.Column("action_id", sa.String(length=100), nullable=True)
        )
        _add_column_if_missing("ingredients", sa.Column("action_payload", sa.Text(), nullable=True))
        _add_column_if_missing(
            "ingredients",
            sa.Column("action_parameters", mysql.JSON(), nullable=True),
        )
        _add_column_if_missing(
            "ingredients",
            sa.Column("expected_duration_sec", sa.Integer(), nullable=True),
        )
        _add_column_if_missing(
            "ingredients",
            sa.Column("timeout_duration_sec", sa.Integer(), nullable=True),
        )
        _add_column_if_missing(
            "ingredients",
            sa.Column("deleted", sa.Boolean(), nullable=True, server_default=sa.text("0")),
        )
        _add_column_if_missing("ingredients", sa.Column("deleted_at", sa.DateTime(), nullable=True))

        ingredient_cols = _column_names("ingredients")
        if legacy_shape:
            op.execute("""
                UPDATE ingredients
                SET
                  source_type = COALESCE(source_type, 'stackstorm'),
                  action_id = COALESCE(action_id, st2_action),
                  action_parameters = CASE
                    WHEN action_parameters IS NOT NULL THEN action_parameters
                    WHEN parameters IS NULL OR parameters = '' THEN NULL
                    WHEN JSON_VALID(parameters) THEN parameters
                    ELSE JSON_OBJECT('raw', parameters)
                  END,
                  expected_duration_sec = COALESCE(expected_duration_sec, expected_time_to_completion),
                  timeout_duration_sec = COALESCE(timeout_duration_sec, timeout),
                  deleted = COALESCE(deleted, 0)
                """)

            if _has_table("recipe_ingredients"):
                op.execute("""
                    INSERT INTO recipe_ingredients (
                      recipe_id,
                      ingredient_id,
                      step_order,
                      on_success,
                      parallel_group,
                      depth
                    )
                    SELECT
                      i.recipe_id,
                      i.id,
                      COALESCE(i.task_order, 1),
                      'continue',
                      0,
                      0
                    FROM ingredients i
                    LEFT JOIN recipe_ingredients ri
                      ON ri.recipe_id = i.recipe_id
                     AND ri.ingredient_id = i.id
                    WHERE i.recipe_id IS NOT NULL
                      AND ri.id IS NULL
                    """)

            _drop_fk_constraints_for_column("ingredients", "recipe_id")
            _drop_indexes_for_column("ingredients", "recipe_id")
            _drop_indexes_for_column("ingredients", "task_order")
            op.drop_column("ingredients", "recipe_id")
            op.drop_column("ingredients", "task_order")
            op.drop_column("ingredients", "st2_action")
            op.drop_column("ingredients", "parameters")
            op.drop_column("ingredients", "expected_time_to_completion")
            op.drop_column("ingredients", "timeout")
        else:
            op.execute("""
                UPDATE ingredients
                SET
                  source_type = COALESCE(source_type, 'manual'),
                  expected_duration_sec = COALESCE(expected_duration_sec, 60),
                  timeout_duration_sec = COALESCE(timeout_duration_sec, 300),
                  deleted = COALESCE(deleted, 0)
                """)

        op.alter_column(
            "ingredients",
            "source_type",
            existing_type=sa.String(length=50),
            nullable=False,
            existing_nullable=True,
        )
        op.alter_column(
            "ingredients",
            "expected_duration_sec",
            existing_type=sa.Integer(),
            nullable=False,
            existing_nullable=True,
        )
        op.alter_column(
            "ingredients",
            "timeout_duration_sec",
            existing_type=sa.Integer(),
            nullable=False,
            existing_nullable=True,
        )
        op.alter_column(
            "ingredients",
            "deleted",
            existing_type=sa.Boolean(),
            nullable=False,
            existing_nullable=True,
        )


def downgrade() -> None:
    # This migration is an in-place schema reconciliation for legacy clusters.
    # Downgrade is intentionally left as a no-op.
    pass
