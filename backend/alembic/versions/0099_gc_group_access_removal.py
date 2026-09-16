"""Retain removed GC App setups without erasing source groups or history.

Revision ID: 0099_gc_group_access_removal
Revises: 0098_notification_saved_delete
"""

from alembic import op
import sqlalchemy as sa

revision = "0099_gc_group_access_removal"
down_revision = "0098_notification_saved_delete"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("gc_group_access", sa.Column("removed_at", sa.DateTime(timezone=True), nullable=True))
    op.create_check_constraint(
        "ck_gc_group_access_removed_disabled",
        "gc_group_access",
        "removed_at IS NULL OR (NOT is_enabled AND revoked_at IS NOT NULL)",
    )


def downgrade() -> None:
    # Discarding the marker would make deliberately removed setups reappear.
    raise RuntimeError("GC App removal history requires schema0099; downgrade refused")
