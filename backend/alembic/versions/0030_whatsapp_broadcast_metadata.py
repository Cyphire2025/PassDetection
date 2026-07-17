"""Add WhatsApp broadcast metadata and support contacts.

Revision ID: 0030_whatsapp_metadata
Revises: 0029_group_require_selfie
Create Date: 2026-07-17
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0030_whatsapp_metadata"
down_revision = "0029_group_require_selfie"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "whatsapp_broadcast_groups",
        sa.Column("organizing_company_name", sa.String(length=255), nullable=False, server_default=""),
    )
    op.add_column(
        "whatsapp_broadcast_groups",
        sa.Column("recipient_opt_in_confirmed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.alter_column("whatsapp_broadcast_groups", "organizing_company_name", server_default=None)

    op.create_table(
        "whatsapp_broadcast_support_contacts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("broadcast_group_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agency_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("phone_number", sa.String(length=64), nullable=False),
        sa.Column("normalized_phone_number", sa.String(length=32), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["agency_id"], ["agencies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["broadcast_group_id"],
            ["whatsapp_broadcast_groups.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "broadcast_group_id",
            "normalized_phone_number",
            name="uq_whatsapp_support_group_phone",
        ),
    )
    op.create_index(
        "ix_whatsapp_broadcast_support_contacts_agency_id",
        "whatsapp_broadcast_support_contacts",
        ["agency_id"],
    )
    op.create_index(
        "ix_whatsapp_broadcast_support_contacts_broadcast_group_id",
        "whatsapp_broadcast_support_contacts",
        ["broadcast_group_id"],
    )
    op.create_index(
        "ix_whatsapp_support_group_order",
        "whatsapp_broadcast_support_contacts",
        ["broadcast_group_id", "sort_order"],
    )

    op.add_column(
        "whatsapp_message_logs",
        sa.Column("template_name", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "whatsapp_message_logs",
        sa.Column("rendered_message", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("whatsapp_message_logs", "rendered_message")
    op.drop_column("whatsapp_message_logs", "template_name")

    op.drop_index("ix_whatsapp_support_group_order", table_name="whatsapp_broadcast_support_contacts")
    op.drop_index(
        "ix_whatsapp_broadcast_support_contacts_broadcast_group_id",
        table_name="whatsapp_broadcast_support_contacts",
    )
    op.drop_index(
        "ix_whatsapp_broadcast_support_contacts_agency_id",
        table_name="whatsapp_broadcast_support_contacts",
    )
    op.drop_table("whatsapp_broadcast_support_contacts")

    op.drop_column("whatsapp_broadcast_groups", "recipient_opt_in_confirmed_at")
    op.drop_column("whatsapp_broadcast_groups", "organizing_company_name")
