"""Persist non-sendable WhatsApp spreadsheet rejection records.

Revision ID: 0042_whatsapp_rejected_contacts
Revises: 0041_global_connects_brand
Create Date: 2026-07-20
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0042_whatsapp_rejected_contacts"
down_revision = "0041_global_connects_brand"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "whatsapp_broadcast_rejected_contacts",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "broadcast_group_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "agency_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("source_file_name", sa.String(length=255), nullable=False),
        sa.Column("sheet_name", sa.String(length=31), nullable=False),
        sa.Column("row_number", sa.Integer(), nullable=False),
        sa.Column("raw_name", sa.String(length=256), nullable=True),
        sa.Column("raw_phone_number", sa.String(length=64), nullable=True),
        sa.Column("reason_code", sa.String(length=32), nullable=False),
        sa.Column("reason", sa.String(length=256), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.CheckConstraint(
            "row_number >= 1",
            name="ck_whatsapp_rejected_contact_row_number",
        ),
        sa.CheckConstraint(
            "reason_code IN "
            "('missing_phone', 'invalid_phone', 'missing_name', 'duplicate_phone')",
            name="ck_whatsapp_rejected_contact_reason_code",
        ),
        sa.ForeignKeyConstraint(
            ["agency_id"],
            ["agencies.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["broadcast_group_id"],
            ["whatsapp_broadcast_groups.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "broadcast_group_id",
            "fingerprint",
            name="uq_whatsapp_rejected_contact_group_fingerprint",
        ),
    )
    op.create_index(
        "ix_whatsapp_broadcast_rejected_contacts_agency_id",
        "whatsapp_broadcast_rejected_contacts",
        ["agency_id"],
    )
    op.create_index(
        "ix_whatsapp_rejected_contacts_group_created",
        "whatsapp_broadcast_rejected_contacts",
        ["broadcast_group_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_whatsapp_rejected_contacts_group_created",
        table_name="whatsapp_broadcast_rejected_contacts",
    )
    op.drop_index(
        "ix_whatsapp_broadcast_rejected_contacts_agency_id",
        table_name="whatsapp_broadcast_rejected_contacts",
    )
    op.drop_table("whatsapp_broadcast_rejected_contacts")
