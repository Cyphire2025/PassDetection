"""Add durable WhatsApp delivery tracking for distributed documents.

Revision ID: 0045_document_whatsapp
Revises: 0044_passport_image_crops
Create Date: 2026-07-22
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0045_document_whatsapp"
down_revision = "0044_passport_image_crops"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "document_whatsapp_deliveries",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agency_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("group_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_batch_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("distributed_document_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("passenger_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("broadcast_group_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("recipient_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("send_batch_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_type", sa.String(length=32), nullable=False),
        sa.Column("document_filename", sa.String(length=255), nullable=False),
        sa.Column("passenger_name", sa.String(length=255), nullable=False),
        sa.Column("passport_number", sa.String(length=32), nullable=True),
        sa.Column("phone_number", sa.String(length=64), nullable=False),
        sa.Column("normalized_phone_number", sa.String(length=32), nullable=False),
        sa.Column("template_name", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("provider_message_id", sa.String(length=255), nullable=True),
        sa.Column("provider_media_id", sa.String(length=255), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("status_updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("provider_status_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["agency_id"], ["agencies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["group_id"], ["client_groups.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["document_batch_id"],
            ["document_distribution_batches.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["distributed_document_id"],
            ["distributed_documents.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(["passenger_id"], ["passport_submissions.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["broadcast_group_id"],
            ["whatsapp_broadcast_groups.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["recipient_id"],
            ["whatsapp_broadcast_recipients.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "distributed_document_id",
            name="uq_document_whatsapp_delivery_document",
        ),
        sa.UniqueConstraint("provider_message_id"),
    )
    for column in (
        "agency_id",
        "group_id",
        "document_batch_id",
        "distributed_document_id",
        "passenger_id",
        "broadcast_group_id",
        "recipient_id",
        "send_batch_id",
        "document_type",
        "normalized_phone_number",
        "status",
    ):
        op.create_index(
            f"ix_document_whatsapp_deliveries_{column}",
            "document_whatsapp_deliveries",
            [column],
        )
    op.create_index(
        "ix_document_whatsapp_delivery_group_status",
        "document_whatsapp_deliveries",
        ["group_id", "status"],
    )
    op.create_index(
        "ix_document_whatsapp_delivery_send_batch",
        "document_whatsapp_deliveries",
        ["send_batch_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_table("document_whatsapp_deliveries")
