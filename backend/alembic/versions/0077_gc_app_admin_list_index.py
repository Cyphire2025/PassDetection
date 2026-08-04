"""Add the tenant-scoped GC App Client Manager list index.

Revision ID: 0077_gc_app_admin_list
Revises: 0076_mobile_push_receipts
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0077_gc_app_admin_list"
down_revision = "0076_mobile_push_receipts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # This table is live while staff create and update accounts. Build without
    # blocking writes; the partial predicate matches every dashboard list page.
    with op.get_context().autocommit_block():
        op.create_index(
            "ix_client_manager_admin_list",
            "client_manager_profiles",
            ["agency_id", "created_at", "id"],
            unique=False,
            postgresql_where=sa.text("deleted_at IS NULL"),
            postgresql_concurrently=True,
            if_not_exists=True,
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.drop_index(
            "ix_client_manager_admin_list",
            table_name="client_manager_profiles",
            postgresql_concurrently=True,
            if_exists=True,
        )
