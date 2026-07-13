"""Add family passport submission metadata.

Revision ID: 0021_family_submissions
Revises: 0020_qr_payloads
Create Date: 2026-07-12
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0021_family_submissions"
down_revision = "0020_qr_payloads"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "passport_submissions",
        sa.Column("submission_mode", sa.String(length=20), nullable=False, server_default="single"),
    )
    op.add_column("passport_submissions", sa.Column("family_group_id", sa.UUID(), nullable=True))
    op.add_column("passport_submissions", sa.Column("family_member_index", sa.Integer(), nullable=True))
    op.add_column("passport_submissions", sa.Column("family_relation", sa.String(length=80), nullable=True))
    op.add_column("passport_submissions", sa.Column("family_gender", sa.String(length=40), nullable=True))
    op.add_column("passport_submissions", sa.Column("family_head_name", sa.String(length=255), nullable=True))
    op.add_column("passport_submissions", sa.Column("family_head_email", sa.String(length=255), nullable=True))
    op.add_column("passport_submissions", sa.Column("family_head_phone", sa.String(length=32), nullable=True))
    op.add_column(
        "passport_submissions",
        sa.Column("family_broadcast_to_member", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.create_index("ix_passport_submissions_family_group_id", "passport_submissions", ["family_group_id"])


def downgrade() -> None:
    op.drop_index("ix_passport_submissions_family_group_id", table_name="passport_submissions")
    op.drop_column("passport_submissions", "family_broadcast_to_member")
    op.drop_column("passport_submissions", "family_head_phone")
    op.drop_column("passport_submissions", "family_head_email")
    op.drop_column("passport_submissions", "family_head_name")
    op.drop_column("passport_submissions", "family_gender")
    op.drop_column("passport_submissions", "family_relation")
    op.drop_column("passport_submissions", "family_member_index")
    op.drop_column("passport_submissions", "family_group_id")
    op.drop_column("passport_submissions", "submission_mode")
