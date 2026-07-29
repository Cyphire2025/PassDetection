"""Store WhatsApp document template content snapshots.

Revision ID: 0062_whatsapp_template_content
Revises: 0061_email_integrations
Create Date: 2026-07-29
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0062_whatsapp_template_content"
down_revision = "0061_email_integrations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "document_whatsapp_deliveries",
        sa.Column(
            "template_parameter_values",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column(
        "document_whatsapp_deliveries",
        "template_parameter_values",
    )
