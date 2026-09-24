"""Opt-in passport back-page ECR checks with durable source-bound outcomes.

Revision ID: 0107_passport_ecr_checks
Revises: 0106_ecr_checker
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0107_passport_ecr_checks"
down_revision = "0106_ecr_checker"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "passport_ecr_checks",
        sa.Column(
            "submission_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("passport_submissions.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("generation", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_storage_key", sa.String(512), nullable=False),
        sa.Column("source_sha256", sa.String(64), nullable=True),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("result", sa.String(24), nullable=True),
        sa.Column("reason", sa.String(255), nullable=True),
        sa.Column("model", sa.String(100), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("provider_attempts", sa.Integer(), nullable=False),
        sa.Column("lease_token", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('queued','processing','completed','failed','disabled')",
            name="ck_passport_ecr_status",
        ),
        sa.CheckConstraint(
            "result IS NULL OR result IN ('ECR','NA','NEEDS_REVIEW')", name="ck_passport_ecr_result"
        ),
    )
    op.create_index(
        "ix_passport_ecr_recovery",
        "passport_ecr_checks",
        ["status", "next_attempt_at", "lease_expires_at"],
    )


def downgrade() -> None:
    op.drop_table("passport_ecr_checks")
