"""Track successful synchronization per mobile installation.

Revision ID: 0074_mobile_device_sync_ack
Revises: 0073_mobile_otp_pending
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0074_mobile_device_sync_ack"
down_revision = "0073_mobile_otp_pending"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Nullable with no server default: on supported PostgreSQL versions this
    # is a metadata-only addition and existing sessions correctly remain
    # "not yet acknowledged" until their next complete sync.
    op.add_column(
        "mobile_device_sessions",
        sa.Column("last_sync_acknowledged_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("mobile_device_sessions", "last_sync_acknowledged_at")
