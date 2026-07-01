"""enterprise async processing and indexes

Revision ID: 0006_enterprise_processing
Revises: 0005_operations_features
Create Date: 2026-06-30 09:30:00.000000

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0006_enterprise_processing"
down_revision = "0005_operations_features"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "passport_processing_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("submission_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("queue_name", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("progress", sa.Float(), nullable=False),
        sa.Column("current_stage", sa.String(length=120), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("celery_task_id", sa.String(length=255), nullable=True),
        sa.Column("cancel_requested", sa.Boolean(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["submission_id"], ["passport_submissions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_passport_processing_jobs_submission_id", "passport_processing_jobs", ["submission_id"])
    op.create_index("ix_passport_processing_jobs_status", "passport_processing_jobs", ["status"])
    op.create_index("ix_passport_processing_jobs_created_at", "passport_processing_jobs", ["created_at"])
    op.create_index("ix_passport_processing_jobs_celery_task_id", "passport_processing_jobs", ["celery_task_id"])
    op.create_index(
        "ix_passport_processing_jobs_status_created_at",
        "passport_processing_jobs",
        ["status", "created_at"],
    )

    op.create_index(
        "ix_passport_submissions_agency_status_created_at",
        "passport_submissions",
        ["agency_id", "status", "created_at"],
    )
    op.create_index(
        "ix_passport_submissions_group_status_created_at",
        "passport_submissions",
        ["group_id", "status", "created_at"],
    )
    op.create_index(
        "ix_client_groups_agency_status_created_at",
        "client_groups",
        ["agency_id", "status", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_client_groups_agency_status_created_at", table_name="client_groups")
    op.drop_index("ix_passport_submissions_group_status_created_at", table_name="passport_submissions")
    op.drop_index("ix_passport_submissions_agency_status_created_at", table_name="passport_submissions")
    op.drop_index("ix_passport_processing_jobs_status_created_at", table_name="passport_processing_jobs")
    op.drop_index("ix_passport_processing_jobs_celery_task_id", table_name="passport_processing_jobs")
    op.drop_index("ix_passport_processing_jobs_created_at", table_name="passport_processing_jobs")
    op.drop_index("ix_passport_processing_jobs_status", table_name="passport_processing_jobs")
    op.drop_index("ix_passport_processing_jobs_submission_id", table_name="passport_processing_jobs")
    op.drop_table("passport_processing_jobs")
