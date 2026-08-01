"""Add durable encrypted tombstones for deferred document cleanup.

Revision ID: 0066_storage_cleanup_jobs
Revises: 0065_ai_travel_inbox
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0066_storage_cleanup_jobs"
down_revision = "0065_ai_travel_inbox"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "storage_cleanup_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agency_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("context_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("storage_keys_ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column(
            "encryption_key_version",
            sa.Integer(),
            server_default="1",
            nullable=False,
        ),
        sa.Column("object_count", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=16),
            server_default="pending",
            nullable=False,
        ),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.String(length=120), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "attempts >= 0",
            name="ck_storage_cleanup_jobs_attempts",
        ),
        sa.CheckConstraint(
            "encryption_key_version >= 1",
            name="ck_storage_cleanup_jobs_key_version",
        ),
        sa.CheckConstraint(
            "object_count > 0",
            name="ck_storage_cleanup_jobs_object_count",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'blocked')",
            name="ck_storage_cleanup_jobs_status",
        ),
        sa.ForeignKeyConstraint(
            ["agency_id"],
            ["agencies.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_storage_cleanup_jobs_due",
        "storage_cleanup_jobs",
        ["status", "next_attempt_at", "created_at"],
    )
    op.create_index(
        "ix_storage_cleanup_jobs_expired_lease",
        "storage_cleanup_jobs",
        ["status", "lease_expires_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_storage_cleanup_jobs_expired_lease",
        table_name="storage_cleanup_jobs",
    )
    op.drop_index("ix_storage_cleanup_jobs_due", table_name="storage_cleanup_jobs")
    op.drop_table("storage_cleanup_jobs")
