"""change user_id to string

Revision ID: a1b2c3d4e5f6
Revises: 3024503057bb
Create Date: 2026-03-14 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = '3024503057bb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Drop all foreign key constraints referencing managed_bot_users.user_id
    op.drop_constraint('bot_instructions_user_id_fkey', 'bot_instructions', type_='foreignkey')
    op.drop_constraint('integrations_user_id_fkey', 'integrations', type_='foreignkey')
    op.drop_constraint('pending_approvals_user_id_fkey', 'pending_approvals', type_='foreignkey')
    op.drop_constraint('user_memory_user_id_fkey', 'user_memory', type_='foreignkey')
    op.drop_constraint('bot_permissions_user_id_fkey', 'bot_permissions', type_='foreignkey')

    # Change user_id column type from UUID to VARCHAR in managed_bot_users
    op.alter_column('managed_bot_users', 'user_id',
                    type_=sa.String(),
                    existing_type=sa.UUID(),
                    postgresql_using='user_id::text')

    # Change user_id FK columns in child tables
    for table in ['bot_instructions', 'integrations', 'pending_approvals', 'user_memory', 'bot_permissions']:
        op.alter_column(table, 'user_id',
                        type_=sa.String(),
                        existing_type=sa.UUID(),
                        postgresql_using='user_id::text')

    # Re-add foreign key constraints
    op.create_foreign_key(None, 'bot_instructions', 'managed_bot_users', ['user_id'], ['user_id'])
    op.create_foreign_key(None, 'integrations', 'managed_bot_users', ['user_id'], ['user_id'])
    op.create_foreign_key(None, 'pending_approvals', 'managed_bot_users', ['user_id'], ['user_id'])
    op.create_foreign_key(None, 'user_memory', 'managed_bot_users', ['user_id'], ['user_id'])
    op.create_foreign_key(None, 'bot_permissions', 'managed_bot_users', ['user_id'], ['user_id'])


def downgrade() -> None:
    # Drop FK constraints
    op.drop_constraint(None, 'bot_instructions', type_='foreignkey')
    op.drop_constraint(None, 'integrations', type_='foreignkey')
    op.drop_constraint(None, 'pending_approvals', type_='foreignkey')
    op.drop_constraint(None, 'user_memory', type_='foreignkey')
    op.drop_constraint(None, 'bot_permissions', type_='foreignkey')

    # Revert to UUID
    for table in ['bot_instructions', 'integrations', 'pending_approvals', 'user_memory', 'bot_permissions']:
        op.alter_column(table, 'user_id',
                        type_=sa.UUID(),
                        existing_type=sa.String(),
                        postgresql_using='user_id::uuid')

    op.alter_column('managed_bot_users', 'user_id',
                    type_=sa.UUID(),
                    existing_type=sa.String(),
                    postgresql_using='user_id::uuid')

    # Re-add FK constraints
    op.create_foreign_key('bot_instructions_user_id_fkey', 'bot_instructions', 'managed_bot_users', ['user_id'], ['user_id'])
    op.create_foreign_key('integrations_user_id_fkey', 'integrations', 'managed_bot_users', ['user_id'], ['user_id'])
    op.create_foreign_key('pending_approvals_user_id_fkey', 'pending_approvals', 'managed_bot_users', ['user_id'], ['user_id'])
    op.create_foreign_key('user_memory_user_id_fkey', 'user_memory', 'managed_bot_users', ['user_id'], ['user_id'])
    op.create_foreign_key('bot_permissions_user_id_fkey', 'bot_permissions', 'managed_bot_users', ['user_id'], ['user_id'])
