"""Preserve imported spreadsheet fields for rejected WhatsApp contacts.

Revision ID: 0043_whatsapp_rejected_imported_fields
Revises: 0042_whatsapp_rejected_contacts
Create Date: 2026-07-21
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0043_whatsapp_rejected_imported_fields"
down_revision = "0042_whatsapp_rejected_contacts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "whatsapp_broadcast_rejected_contacts",
        sa.Column(
            "imported_fields",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column(
        "whatsapp_broadcast_rejected_contacts",
        "imported_fields",
    )
