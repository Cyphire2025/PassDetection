"""Retain WhatsApp broadcast lists in a restorable archive.

Revision ID: 0100_whatsapp_group_archive
Revises: 0099_gc_group_access_removal
"""

from alembic import op
import sqlalchemy as sa

revision = "0100_whatsapp_group_archive"
down_revision = "0099_gc_group_access_removal"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "whatsapp_broadcast_groups",
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_whatsapp_groups_agency_archive_created",
        "whatsapp_broadcast_groups",
        ["agency_id", "archived_at", "created_at"],
    )


def downgrade() -> None:
    # Losing this marker would silently reactivate deliberately archived lists.
    raise RuntimeError("WhatsApp archive history requires schema0100; downgrade refused")
