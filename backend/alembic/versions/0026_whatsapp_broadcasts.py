"""Add WhatsApp broadcast groups.

Revision ID: 0026_whatsapp_broadcasts
Revises: 0025_split_manager_staff_roles
Create Date: 2026-07-15 10:30:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0026_whatsapp_broadcasts"
down_revision = "0025_split_manager_staff_roles"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "whatsapp_broadcast_groups",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agency_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["agency_id"], ["agencies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_whatsapp_broadcast_groups_agency_id", "whatsapp_broadcast_groups", ["agency_id"])
    op.create_index("ix_whatsapp_broadcast_groups_created_by_user_id", "whatsapp_broadcast_groups", ["created_by_user_id"])
    op.create_index("ix_whatsapp_broadcast_groups_agency_created", "whatsapp_broadcast_groups", ["agency_id", "created_at"])

    op.create_table(
        "whatsapp_broadcast_recipients",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("broadcast_group_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agency_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=True),
        sa.Column("phone_number", sa.String(length=64), nullable=False),
        sa.Column("normalized_phone_number", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["agency_id"], ["agencies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["broadcast_group_id"], ["whatsapp_broadcast_groups.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("broadcast_group_id", "normalized_phone_number", name="uq_whatsapp_recipient_group_phone"),
    )
    op.create_index("ix_whatsapp_broadcast_recipients_agency_id", "whatsapp_broadcast_recipients", ["agency_id"])
    op.create_index("ix_whatsapp_broadcast_recipients_broadcast_group_id", "whatsapp_broadcast_recipients", ["broadcast_group_id"])
    op.create_index("ix_whatsapp_broadcast_recipients_normalized_phone_number", "whatsapp_broadcast_recipients", ["normalized_phone_number"])
    op.create_index("ix_whatsapp_recipients_group_created", "whatsapp_broadcast_recipients", ["broadcast_group_id", "created_at"])

    op.create_table(
        "whatsapp_message_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("broadcast_group_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("recipient_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agency_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("message_type", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("provider_message_id", sa.String(length=255), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["agency_id"], ["agencies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["broadcast_group_id"], ["whatsapp_broadcast_groups.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["recipient_id"], ["whatsapp_broadcast_recipients.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_whatsapp_message_logs_agency_id", "whatsapp_message_logs", ["agency_id"])
    op.create_index("ix_whatsapp_message_logs_broadcast_group_id", "whatsapp_message_logs", ["broadcast_group_id"])
    op.create_index("ix_whatsapp_message_logs_recipient_id", "whatsapp_message_logs", ["recipient_id"])
    op.create_index("ix_whatsapp_message_logs_group_created", "whatsapp_message_logs", ["broadcast_group_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_whatsapp_message_logs_group_created", table_name="whatsapp_message_logs")
    op.drop_index("ix_whatsapp_message_logs_recipient_id", table_name="whatsapp_message_logs")
    op.drop_index("ix_whatsapp_message_logs_broadcast_group_id", table_name="whatsapp_message_logs")
    op.drop_index("ix_whatsapp_message_logs_agency_id", table_name="whatsapp_message_logs")
    op.drop_table("whatsapp_message_logs")

    op.drop_index("ix_whatsapp_recipients_group_created", table_name="whatsapp_broadcast_recipients")
    op.drop_index("ix_whatsapp_broadcast_recipients_normalized_phone_number", table_name="whatsapp_broadcast_recipients")
    op.drop_index("ix_whatsapp_broadcast_recipients_broadcast_group_id", table_name="whatsapp_broadcast_recipients")
    op.drop_index("ix_whatsapp_broadcast_recipients_agency_id", table_name="whatsapp_broadcast_recipients")
    op.drop_table("whatsapp_broadcast_recipients")

    op.drop_index("ix_whatsapp_broadcast_groups_agency_created", table_name="whatsapp_broadcast_groups")
    op.drop_index("ix_whatsapp_broadcast_groups_created_by_user_id", table_name="whatsapp_broadcast_groups")
    op.drop_index("ix_whatsapp_broadcast_groups_agency_id", table_name="whatsapp_broadcast_groups")
    op.drop_table("whatsapp_broadcast_groups")
