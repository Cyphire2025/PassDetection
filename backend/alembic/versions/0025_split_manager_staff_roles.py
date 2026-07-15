"""Split manager and staff user roles.

Revision ID: 0025_split_manager_staff_roles
Revises: 0024_document_rename_batch_title
Create Date: 2026-07-14 23:10:00.000000
"""

from __future__ import annotations

from alembic import op


revision = "0025_split_manager_staff_roles"
down_revision = "0024_document_rename_batch_title"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE user_role_enum ADD VALUE IF NOT EXISTS 'agency_manager'")
    op.execute("UPDATE users SET role = 'agency_manager' WHERE role = 'agency_staff'")


def downgrade() -> None:
    op.execute("UPDATE users SET role = 'agency_staff' WHERE role = 'agency_manager'")
