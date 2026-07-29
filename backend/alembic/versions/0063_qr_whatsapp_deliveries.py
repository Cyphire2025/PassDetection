"""Add durable per-token WhatsApp delivery state for passenger QR codes.

Revision ID: 0063_qr_whatsapp
Revises: 0062_whatsapp_template_content
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0063_qr_whatsapp"
down_revision = "0062_whatsapp_template_content"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "passenger_qr_whatsapp_deliveries",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agency_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("group_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("passenger_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("qr_token_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "broadcast_group_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column("recipient_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("send_batch_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("passenger_name", sa.String(length=255), nullable=False),
        sa.Column("passport_number", sa.String(length=32), nullable=True),
        sa.Column("phone_number", sa.String(length=64), nullable=False),
        sa.Column("normalized_phone_number", sa.String(length=32), nullable=False),
        sa.Column("template_name", sa.String(length=255), nullable=False),
        sa.Column(
            "template_parameter_values",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("provider_message_id", sa.String(length=255), nullable=True),
        sa.Column("provider_media_id", sa.String(length=255), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("status_updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("provider_status_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["agency_id"],
            ["agencies.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["group_id"],
            ["client_groups.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["passenger_id"],
            ["passport_submissions.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["qr_token_id"],
            ["passenger_qr_tokens.id"],
            ondelete="CASCADE",
        ),
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
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "provider_message_id",
            name="uq_passenger_qr_whatsapp_deliveries_provider_message_id",
        ),
        sa.UniqueConstraint(
            "qr_token_id",
            name="uq_passenger_qr_whatsapp_delivery_token",
        ),
    )
    for column in (
        "agency_id",
        "group_id",
        "passenger_id",
        "qr_token_id",
        "broadcast_group_id",
        "recipient_id",
        "send_batch_id",
        "normalized_phone_number",
        "status",
    ):
        op.create_index(
            f"ix_passenger_qr_whatsapp_deliveries_{column}",
            "passenger_qr_whatsapp_deliveries",
            [column],
        )
    op.create_index(
        "ix_passenger_qr_whatsapp_delivery_group_status",
        "passenger_qr_whatsapp_deliveries",
        ["group_id", "status"],
    )
    op.create_index(
        "ix_passenger_qr_whatsapp_delivery_send_batch",
        "passenger_qr_whatsapp_deliveries",
        ["send_batch_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_table("passenger_qr_whatsapp_deliveries")
