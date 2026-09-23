"""Durable ECR checker batches and per-image outcomes.

Revision ID: 0106_ecr_checker
Revises: 0105_whatsapp_phone_overrides
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0106_ecr_checker"
down_revision = "0105_whatsapp_phone_overrides"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ecr_batches",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "agency_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agencies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "created_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("title", sa.String(160), nullable=False),
        sa.Column("expected_count", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("lease_token", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("expected_count BETWEEN 1 AND 1000", name="ck_ecr_batch_count"),
    )
    op.create_index("ix_ecr_batch_agency_created", "ecr_batches", ["agency_id", "created_at"])
    op.create_index("ix_ecr_batch_recovery", "ecr_batches", ["status", "lease_expires_at"])
    op.create_table(
        "ecr_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "batch_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("ecr_batches.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("client_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("original_filename", sa.String(255), nullable=False),
        sa.Column("object_key", sa.String(512), nullable=True),
        sa.Column("content_type", sa.String(80), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("result", sa.String(24), nullable=True),
        sa.Column("reason", sa.String(255), nullable=True),
        sa.Column("model", sa.String(100), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("batch_id", "client_id", name="uq_ecr_item_client"),
    )
    op.create_index("ix_ecr_items_batch_status", "ecr_items", ["batch_id", "status"])


def downgrade() -> None:
    op.drop_table("ecr_items")
    op.drop_table("ecr_batches")
