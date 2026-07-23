"""Add durable background jobs for slow Visa AI image generation.

Revision ID: 0049_visa_ai_image_jobs
Revises: 0048_visa_ai_image_library
Create Date: 2026-07-23
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0049_visa_ai_image_jobs"
down_revision = "0048_visa_ai_image_library"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "passport_visa_ai_image_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("submission_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("original_source_storage_key", sa.String(length=512), nullable=False),
        sa.Column("input_storage_key", sa.String(length=512), nullable=False),
        sa.Column("prompt", sa.String(length=1000), nullable=False),
        sa.Column("prompt_sha256", sa.String(length=64), nullable=False),
        sa.Column("requested_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "status",
            sa.String(length=32),
            server_default="queued",
            nullable=False,
        ),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("max_attempts", sa.Integer(), server_default="2", nullable=False),
        sa.Column("celery_task_id", sa.String(length=255), nullable=True),
        sa.Column("result_image_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column("error_message", sa.String(length=320), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed')",
            name="ck_passport_visa_ai_image_jobs_status",
        ),
        sa.CheckConstraint(
            "attempts >= 0",
            name="ck_passport_visa_ai_image_jobs_attempts",
        ),
        sa.CheckConstraint(
            "max_attempts BETWEEN 1 AND 3",
            name="ck_passport_visa_ai_image_jobs_max_attempts",
        ),
        sa.ForeignKeyConstraint(
            ["requested_by_user_id"],
            ["users.id"],
            name="fk_passport_visa_ai_image_jobs_requested_by",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["result_image_id"],
            ["passport_visa_ai_images.id"],
            name="fk_passport_visa_ai_image_jobs_result",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["submission_id"],
            ["passport_submissions.id"],
            name="fk_passport_visa_ai_image_jobs_submission",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_passport_visa_ai_image_jobs"),
    )
    op.create_index(
        "ix_passport_visa_ai_image_jobs_submission_id",
        "passport_visa_ai_image_jobs",
        ["submission_id"],
        unique=False,
    )
    op.create_index(
        "ix_passport_visa_ai_image_jobs_requested_by_user_id",
        "passport_visa_ai_image_jobs",
        ["requested_by_user_id"],
        unique=False,
    )
    op.create_index(
        "ix_passport_visa_ai_image_jobs_celery_task_id",
        "passport_visa_ai_image_jobs",
        ["celery_task_id"],
        unique=False,
    )
    op.create_index(
        "ix_passport_visa_ai_image_jobs_result_image_id",
        "passport_visa_ai_image_jobs",
        ["result_image_id"],
        unique=False,
    )
    op.create_index(
        "ix_passport_visa_ai_image_jobs_status",
        "passport_visa_ai_image_jobs",
        ["status"],
        unique=False,
    )
    op.create_index(
        "ix_passport_visa_ai_image_jobs_created_at",
        "passport_visa_ai_image_jobs",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        "ix_passport_visa_ai_image_jobs_submission_created",
        "passport_visa_ai_image_jobs",
        ["submission_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "uq_passport_visa_ai_image_jobs_active_submission",
        "passport_visa_ai_image_jobs",
        ["submission_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('queued', 'running')"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_passport_visa_ai_image_jobs_active_submission",
        table_name="passport_visa_ai_image_jobs",
    )
    op.drop_index(
        "ix_passport_visa_ai_image_jobs_submission_created",
        table_name="passport_visa_ai_image_jobs",
    )
    op.drop_index(
        "ix_passport_visa_ai_image_jobs_created_at",
        table_name="passport_visa_ai_image_jobs",
    )
    op.drop_index(
        "ix_passport_visa_ai_image_jobs_status",
        table_name="passport_visa_ai_image_jobs",
    )
    op.drop_index(
        "ix_passport_visa_ai_image_jobs_result_image_id",
        table_name="passport_visa_ai_image_jobs",
    )
    op.drop_index(
        "ix_passport_visa_ai_image_jobs_celery_task_id",
        table_name="passport_visa_ai_image_jobs",
    )
    op.drop_index(
        "ix_passport_visa_ai_image_jobs_requested_by_user_id",
        table_name="passport_visa_ai_image_jobs",
    )
    op.drop_index(
        "ix_passport_visa_ai_image_jobs_submission_id",
        table_name="passport_visa_ai_image_jobs",
    )
    op.drop_table("passport_visa_ai_image_jobs")
