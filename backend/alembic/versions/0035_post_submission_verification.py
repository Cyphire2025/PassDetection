"""Add canonical passport statuses and durable post-submit verification.

Revision ID: 0035_post_submit_verify
Revises: 0034_extraction_conflicts
Create Date: 2026-07-17
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0035_post_submit_verify"
down_revision = "0034_extraction_conflicts"
branch_labels = None
depends_on = None

_NEW_STATUS_VALUES = (
    "pending_extraction",
    "extracting",
    "ready_for_client_review",
    "submitted",
    "ai_approved",
    "needs_review",
    "staff_approved",
)


def upgrade() -> None:
    for status_value in _NEW_STATUS_VALUES:
        op.execute(
            f"ALTER TYPE submission_status_enum "
            f"ADD VALUE IF NOT EXISTS '{status_value}'"
        )

    op.add_column(
        "passport_submissions",
        sa.Column(
            "post_submission_verification",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )
    op.add_column(
        "passport_submissions",
        sa.Column(
            "post_submission_verification_revision",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "passport_submissions",
        sa.Column("post_submission_verified_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "passport_submissions",
        sa.Column(
            "verification_reviewed_by_user_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.add_column(
        "passport_submissions",
        sa.Column("verification_reviewer_name", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "passport_submissions",
        sa.Column("verification_reviewed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_passport_verification_reviewer",
        "passport_submissions",
        "users",
        ["verification_reviewed_by_user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_passport_submissions_verification_reviewed_by_user_id",
        "passport_submissions",
        ["verification_reviewed_by_user_id"],
    )
    op.create_check_constraint(
        "ck_passport_submissions_post_verification_revision",
        "passport_submissions",
        "post_submission_verification_revision >= 0",
    )

    op.create_table(
        "passport_post_submission_verification_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("submission_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("verification_revision", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="queued", nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("max_attempts", sa.Integer(), server_default="3", nullable=False),
        sa.Column("celery_task_id", sa.String(length=255), nullable=True),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "verification_revision >= 1",
            name="ck_passport_post_verification_revision",
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed')",
            name="ck_passport_post_verification_job_status",
        ),
        sa.CheckConstraint(
            "attempts >= 0",
            name="ck_passport_post_verification_job_attempts",
        ),
        sa.CheckConstraint(
            "max_attempts BETWEEN 1 AND 3",
            name="ck_passport_post_verification_job_max_attempts",
        ),
        sa.ForeignKeyConstraint(
            ["submission_id"],
            ["passport_submissions.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "submission_id",
            "verification_revision",
            name="uq_passport_post_verification_job_revision",
        ),
    )
    op.create_index(
        "ix_passport_post_submission_verification_jobs_submission_id",
        "passport_post_submission_verification_jobs",
        ["submission_id"],
    )
    op.create_index(
        "ix_passport_post_submission_verification_jobs_status",
        "passport_post_submission_verification_jobs",
        ["status"],
    )
    op.create_index(
        "ix_passport_post_submission_verification_jobs_celery_task_id",
        "passport_post_submission_verification_jobs",
        ["celery_task_id"],
    )
    op.create_index(
        "ix_passport_post_submission_verification_jobs_created_at",
        "passport_post_submission_verification_jobs",
        ["created_at"],
    )


def downgrade() -> None:
    # Restore values understood by the previous application before its model is
    # brought back. PostgreSQL enum labels themselves are intentionally kept.
    status_fallbacks = {
        "pending_extraction": "uploaded",
        "extracting": "processing",
        "ready_for_client_review": "review_required",
        "submitted": "client_submitted",
        "needs_review": "client_submitted",
        "ai_approved": "confirmed",
        "staff_approved": "confirmed",
    }
    for current, legacy in status_fallbacks.items():
        op.execute(
            sa.text(
                "UPDATE passport_submissions "
                "SET status = CAST(:legacy AS submission_status_enum) "
                "WHERE status = CAST(:current AS submission_status_enum)"
            ).bindparams(current=current, legacy=legacy)
        )

    op.drop_table("passport_post_submission_verification_jobs")
    op.drop_constraint(
        "ck_passport_submissions_post_verification_revision",
        "passport_submissions",
        type_="check",
    )
    op.drop_index(
        "ix_passport_submissions_verification_reviewed_by_user_id",
        table_name="passport_submissions",
    )
    op.drop_constraint(
        "fk_passport_verification_reviewer",
        "passport_submissions",
        type_="foreignkey",
    )
    op.drop_column("passport_submissions", "verification_reviewed_at")
    op.drop_column("passport_submissions", "verification_reviewer_name")
    op.drop_column("passport_submissions", "verification_reviewed_by_user_id")
    op.drop_column("passport_submissions", "post_submission_verified_at")
    op.drop_column("passport_submissions", "post_submission_verification_revision")
    op.drop_column("passport_submissions", "post_submission_verification")
    # PostgreSQL enum values are intentionally retained: removing enum labels is
    # destructive and would break backward-compatible reads during rollback.
