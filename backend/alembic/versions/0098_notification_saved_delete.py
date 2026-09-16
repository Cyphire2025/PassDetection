"""Remove saved notifications without erasing historical sends or delivery.

Revision ID: 0098_notification_saved_delete
Revises: 0097_authored_notifications
"""

from alembic import op
import sqlalchemy as sa

revision = "0098_notification_saved_delete"
down_revision = "0097_authored_notifications"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "gc_notification_drafts", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "gc_notification_drafts", sa.Column("deleted_by_user_id", sa.UUID(), nullable=True)
    )
    op.create_foreign_key(
        "fk_gc_notification_draft_deleted_by",
        "gc_notification_drafts",
        "users",
        ["deleted_by_user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_gc_notification_saved_page",
        "gc_notification_drafts",
        ["agency_id", "created_at", "id"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )


def downgrade() -> None:
    # Removing the tombstone would resurrect deleted saved messages for older callers.
    raise RuntimeError("Saved notification deletion history requires schema0098; downgrade refused")
