"""add active and last_used_at to integrations

Revision ID: b9c1d2e3f4a5
Revises: f4780f4e9fa2
Create Date: 2026-03-20 00:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'b9c1d2e3f4a5'
down_revision: Union[str, Sequence[str], None] = 'f4780f4e9fa2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'integrations',
        sa.Column('active', sa.Boolean(), nullable=False, server_default=sa.text('true'))
    )
    op.add_column(
        'integrations',
        sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True)
    )
    op.create_unique_constraint(
        'uq_integrations_user_service', 'integrations', ['user_id', 'service']
    )


def downgrade() -> None:
    op.drop_constraint('uq_integrations_user_service', 'integrations', type_='unique')
    op.drop_column('integrations', 'last_used_at')
    op.drop_column('integrations', 'active')
