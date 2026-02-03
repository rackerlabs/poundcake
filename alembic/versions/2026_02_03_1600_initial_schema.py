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
revision: str = '2026_02_03_1600'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create recipes table
    op.create_table('recipes',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('enabled', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_recipes_id'), 'recipes', ['id'], unique=False)
    op.create_index(op.f('ix_recipes_name'), 'recipes', ['name'], unique=True)
    
    # Create ingredients table
    op.create_table('ingredients',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('recipe_id', sa.Integer(), nullable=False),
        sa.Column('task_id', sa.String(length=100), nullable=False),
        sa.Column('task_name', sa.String(length=255), nullable=False),
        sa.Column('task_order', sa.Integer(), nullable=False),
        sa.Column('is_blocking', sa.Boolean(), nullable=False),
        sa.Column('st2_action', sa.String(length=255), nullable=False),
        sa.Column('parameters', mysql.LONGTEXT(), nullable=True),
        sa.Column('expected_time_to_completion', sa.Integer(), nullable=False),
        sa.Column('timeout', sa.Integer(), nullable=False),
        sa.Column('retry_count', sa.Integer(), nullable=False),
        sa.Column('retry_delay', sa.Integer(), nullable=False),
        sa.Column('on_failure', sa.String(length=50), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['recipe_id'], ['recipes.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_ingredients_id'), 'ingredients', ['id'], unique=False)
    op.create_index(op.f('ix_ingredients_task_id'), 'ingredients', ['task_id'], unique=False)
    op.create_index('idx_recipe_order', 'ingredients', ['recipe_id', 'task_order'], unique=False)
    
    # Create alerts table
    op.create_table('alerts',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('req_id', sa.String(length=100), nullable=False),
        sa.Column('fingerprint', sa.String(length=255), nullable=False),
        sa.Column('alert_status', sa.String(length=50), nullable=False),
        sa.Column('processing_status', sa.String(length=50), nullable=False),
        sa.Column('alert_name', sa.String(length=255), nullable=False),
        sa.Column('group_name', sa.String(length=255), nullable=True),
        sa.Column('severity', sa.String(length=50), nullable=True),
        sa.Column('instance', sa.String(length=255), nullable=True),
        sa.Column('prometheus', sa.String(length=255), nullable=True),
        sa.Column('labels', mysql.LONGTEXT(), nullable=False),
        sa.Column('annotations', mysql.LONGTEXT(), nullable=True),
        sa.Column('starts_at', sa.DateTime(), nullable=False),
        sa.Column('ends_at', sa.DateTime(), nullable=True),
        sa.Column('generator_url', sa.Text(), nullable=True),
        sa.Column('counter', sa.Integer(), nullable=False),
        sa.Column('ticket_number', sa.String(length=100), nullable=True),
        sa.Column('raw_data', mysql.LONGTEXT(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('fingerprint')
    )
    op.create_index(op.f('ix_alerts_alert_name'), 'alerts', ['alert_name'], unique=False)
    op.create_index(op.f('ix_alerts_alert_status'), 'alerts', ['alert_status'], unique=False)
    op.create_index(op.f('ix_alerts_created_at'), 'alerts', ['created_at'], unique=False)
    op.create_index(op.f('ix_alerts_fingerprint'), 'alerts', ['fingerprint'], unique=True)
    op.create_index(op.f('ix_alerts_group_name'), 'alerts', ['group_name'], unique=False)
    op.create_index(op.f('ix_alerts_id'), 'alerts', ['id'], unique=False)
    op.create_index(op.f('ix_alerts_instance'), 'alerts', ['instance'], unique=False)
    op.create_index(op.f('ix_alerts_processing_status'), 'alerts', ['processing_status'], unique=False)
    op.create_index(op.f('ix_alerts_req_id'), 'alerts', ['req_id'], unique=False)
    op.create_index(op.f('ix_alerts_severity'), 'alerts', ['severity'], unique=False)
    op.create_index(op.f('ix_alerts_ticket_number'), 'alerts', ['ticket_number'], unique=False)
    
    # Create ovens table
    op.create_table('ovens',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('req_id', sa.String(length=100), nullable=False),
        sa.Column('alert_id', sa.Integer(), nullable=True),
        sa.Column('recipe_id', sa.Integer(), nullable=False),
        sa.Column('ingredient_id', sa.Integer(), nullable=False),
        sa.Column('processing_status', sa.String(length=50), nullable=False),
        sa.Column('task_order', sa.Integer(), nullable=False),
        sa.Column('is_blocking', sa.Boolean(), nullable=False),
        sa.Column('action_id', sa.String(length=255), nullable=True),
        sa.Column('st2_status', sa.String(length=50), nullable=True),
        sa.Column('expected_duration', sa.Integer(), nullable=True),
        sa.Column('actual_duration', sa.Integer(), nullable=True),
        sa.Column('started_at', sa.DateTime(), nullable=True),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.Column('action_result', mysql.LONGTEXT(), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('retry_attempt', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['alert_id'], ['alerts.id'], ),
        sa.ForeignKeyConstraint(['ingredient_id'], ['ingredients.id'], ),
        sa.ForeignKeyConstraint(['recipe_id'], ['recipes.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_ovens_action_id'), 'ovens', ['action_id'], unique=False)
    op.create_index(op.f('ix_ovens_id'), 'ovens', ['id'], unique=False)
    op.create_index(op.f('ix_ovens_processing_status'), 'ovens', ['processing_status'], unique=False)
    op.create_index(op.f('ix_ovens_req_id'), 'ovens', ['req_id'], unique=False)
    op.create_index(op.f('ix_ovens_task_order'), 'ovens', ['task_order'], unique=False)
    op.create_index('idx_oven_task_order', 'ovens', ['recipe_id', 'task_order'], unique=False)


def downgrade() -> None:
    op.drop_index('idx_oven_task_order', table_name='ovens')
    op.drop_index(op.f('ix_ovens_task_order'), table_name='ovens')
    op.drop_index(op.f('ix_ovens_req_id'), table_name='ovens')
    op.drop_index(op.f('ix_ovens_processing_status'), table_name='ovens')
    op.drop_index(op.f('ix_ovens_id'), table_name='ovens')
    op.drop_index(op.f('ix_ovens_action_id'), table_name='ovens')
    op.drop_table('ovens')
    
    op.drop_index(op.f('ix_alerts_ticket_number'), table_name='alerts')
    op.drop_index(op.f('ix_alerts_severity'), table_name='alerts')
    op.drop_index(op.f('ix_alerts_req_id'), table_name='alerts')
    op.drop_index(op.f('ix_alerts_processing_status'), table_name='alerts')
    op.drop_index(op.f('ix_alerts_instance'), table_name='alerts')
    op.drop_index(op.f('ix_alerts_id'), table_name='alerts')
    op.drop_index(op.f('ix_alerts_group_name'), table_name='alerts')
    op.drop_index(op.f('ix_alerts_fingerprint'), table_name='alerts')
    op.drop_index(op.f('ix_alerts_created_at'), table_name='alerts')
    op.drop_index(op.f('ix_alerts_alert_status'), table_name='alerts')
    op.drop_index(op.f('ix_alerts_alert_name'), table_name='alerts')
    op.drop_table('alerts')
    
    op.drop_index('idx_recipe_order', table_name='ingredients')
    op.drop_index(op.f('ix_ingredients_task_id'), table_name='ingredients')
    op.drop_index(op.f('ix_ingredients_id'), table_name='ingredients')
    op.drop_table('ingredients')
    
    op.drop_index(op.f('ix_recipes_name'), table_name='recipes')
    op.drop_index(op.f('ix_recipes_id'), table_name='recipes')
    op.drop_table('recipes')
