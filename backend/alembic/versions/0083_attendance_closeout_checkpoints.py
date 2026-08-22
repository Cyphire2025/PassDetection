"""Add count-only attendance closeout checkpoints.

Revision ID: 0083_attendance_closeout
Revises: 0082_canonical_trip_timezone

One latest row is retained per canonical activity and coordinator account. The
table deliberately stores no QR, passenger, event, installation, or device
identifier.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0083_attendance_closeout"
down_revision = "0082_canonical_trip_timezone"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "attendance_closeout_checkpoints",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "coordinator_user_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("pending_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("sending_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("retryable_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("needs_review_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "unreviewed_rejected_count",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column("oldest_pending_age_seconds", sa.Integer(), nullable=True),
        sa.Column(
            "reported_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "pending_count >= 0 AND sending_count >= 0 AND retryable_count >= 0 "
            "AND needs_review_count >= 0 AND unreviewed_rejected_count >= 0",
            name="ck_attendance_closeout_checkpoint_nonnegative_counts",
        ),
        sa.CheckConstraint(
            "((pending_count + sending_count + retryable_count = 0 "
            "AND oldest_pending_age_seconds IS NULL) OR "
            "(pending_count + sending_count + retryable_count > 0 "
            "AND oldest_pending_age_seconds >= 0))",
            name="ck_attendance_closeout_checkpoint_oldest_pending",
        ),
        sa.ForeignKeyConstraint(
            ["coordinator_user_id"],
            ["users.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["attendance_sessions.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "session_id",
            "coordinator_user_id",
            name="uq_attendance_closeout_checkpoint_coordinator",
        ),
    )
    op.create_index(
        "ix_attendance_closeout_checkpoints_coordinator_user_id",
        "attendance_closeout_checkpoints",
        ["coordinator_user_id"],
    )
    op.create_index(
        "ix_attendance_closeout_checkpoints_session_id",
        "attendance_closeout_checkpoints",
        ["session_id"],
    )
    op.create_index(
        "ix_attendance_closeout_checkpoints_session_reported",
        "attendance_closeout_checkpoints",
        ["session_id", "reported_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_attendance_closeout_checkpoints_session_reported",
        table_name="attendance_closeout_checkpoints",
    )
    op.drop_index(
        "ix_attendance_closeout_checkpoints_session_id",
        table_name="attendance_closeout_checkpoints",
    )
    op.drop_index(
        "ix_attendance_closeout_checkpoints_coordinator_user_id",
        table_name="attendance_closeout_checkpoints",
    )
    op.drop_table("attendance_closeout_checkpoints")
