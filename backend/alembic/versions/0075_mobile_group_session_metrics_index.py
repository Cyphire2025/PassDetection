"""Index group-scoped live mobile-session metric reads.

Revision ID: 0075_mobile_session_metrics_idx
Revises: 0074_mobile_device_sync_ack
"""

from __future__ import annotations

from alembic import op

revision = "0075_mobile_session_metrics_idx"
down_revision = "0074_mobile_device_sync_ack"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # This is intentionally a separate revision from the new nullable column:
    # the autocommit required by CREATE INDEX CONCURRENTLY can then fail/retry
    # without replaying a previously committed ALTER TABLE.
    with op.get_context().autocommit_block():
        op.create_index(
            "ix_mobile_session_group_status_expiry",
            "mobile_device_sessions",
            ["agency_id", "selected_gc_group_access_id", "status", "expires_at"],
            unique=False,
            postgresql_concurrently=True,
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.drop_index(
            "ix_mobile_session_group_status_expiry",
            table_name="mobile_device_sessions",
            postgresql_concurrently=True,
        )
