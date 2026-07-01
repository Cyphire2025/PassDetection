"""client review submission

Revision ID: 0003_client_review_submission
Revises: 0002
Create Date: 2026-06-29 18:30:00.000000

"""

from alembic import op
import sqlalchemy as sa


revision = "0003_client_review_submission"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE submission_status_enum ADD VALUE IF NOT EXISTS 'client_submitted'")
    op.add_column("passport_submissions", sa.Column("client_phone", sa.String(length=32), nullable=True))
    op.add_column("passport_submissions", sa.Column("client_reviewed_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_passport_submissions_group_email", "passport_submissions", ["group_id", "client_email"], unique=False)
    op.create_index("ix_passport_submissions_group_phone", "passport_submissions", ["group_id", "client_phone"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_passport_submissions_group_phone", table_name="passport_submissions")
    op.drop_index("ix_passport_submissions_group_email", table_name="passport_submissions")
    op.drop_column("passport_submissions", "client_reviewed_at")
    op.drop_column("passport_submissions", "client_phone")
