"""add_dynamic_agents_and_generated_tools

Revision ID: 67443b80c5a3
Revises:
Create Date: 2026-05-15 16:03:47.741328

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '67443b80c5a3'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'dynamic_agents',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('system_prompt', sa.Text(), nullable=False),
        sa.Column('keyword_rules', sa.JSON(), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('created_by', sa.Integer(), nullable=True),
        sa.Column('test_results', sa.JSON(), nullable=True),
        sa.Column('activated_at', sa.DateTime(), nullable=True),
        sa.Column('activated_by', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['activated_by'], ['users.id']),
        sa.ForeignKeyConstraint(['created_by'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_dynamic_agents_id'), 'dynamic_agents', ['id'], unique=False)
    op.create_index(op.f('ix_dynamic_agents_name'), 'dynamic_agents', ['name'], unique=True)

    op.create_table(
        'generated_tools',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('agent_id', sa.Integer(), nullable=False),
        sa.Column('tool_name', sa.String(length=100), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('code_template', sa.Text(), nullable=False),
        sa.Column('parameters_schema', sa.JSON(), nullable=False),
        sa.Column('ast_validation_passed', sa.Boolean(), nullable=False),
        sa.Column('sandbox_test_passed', sa.Boolean(), nullable=False),
        sa.Column('test_log', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['agent_id'], ['dynamic_agents.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_generated_tools_id'), 'generated_tools', ['id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_generated_tools_id'), table_name='generated_tools')
    op.drop_table('generated_tools')
    op.drop_index(op.f('ix_dynamic_agents_name'), table_name='dynamic_agents')
    op.drop_index(op.f('ix_dynamic_agents_id'), table_name='dynamic_agents')
    op.drop_table('dynamic_agents')
