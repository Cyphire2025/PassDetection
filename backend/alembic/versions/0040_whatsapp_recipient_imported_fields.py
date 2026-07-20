"""Persist bounded spreadsheet fields for WhatsApp recipients.

Revision ID: 0040_whatsapp_recipient_fields
Revises: 0039_group_whatsapp_links
Create Date: 2026-07-20
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0040_whatsapp_recipient_fields"
down_revision = "0039_group_whatsapp_links"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "whatsapp_broadcast_recipients",
        sa.Column(
            "imported_fields",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column(
        "whatsapp_broadcast_recipients",
        "imported_fields",
    )
