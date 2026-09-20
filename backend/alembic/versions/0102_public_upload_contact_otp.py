"""Require a scoped WhatsApp contact proof for public passport submissions.

Revision ID: 0102_public_upload_contact_otp
Revises: 0101_client_group_import_only
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0102_public_upload_contact_otp"
down_revision = "0101_client_group_import_only"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "public_upload_contact_challenges",
        sa.Column("submission_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("group_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("upload_session_hash", sa.String(64), nullable=False),
        sa.Column("email_hash", sa.String(64), nullable=False),
        sa.Column("phone_number", sa.String(32), nullable=False),
        sa.Column("code_hash", sa.String(64), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resend_available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("proof_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["submission_id"], ["passport_submissions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["group_id"], ["client_groups.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("id", name="uq_public_upload_contact_challenge_id"),
        sa.CheckConstraint(
            "status IN ('sending', 'pending', 'failed', 'locked', 'verified', 'consumed')",
            name="ck_public_upload_contact_challenge_status",
        ),
        sa.CheckConstraint("attempt_count >= 0", name="ck_public_upload_contact_attempts"),
    )


def downgrade() -> None:
    op.drop_table("public_upload_contact_challenges")
