"""Persist WhatsApp template snapshots and guard explicit resend claims.

Revision ID: 0038_whatsapp_resend
Revises: 0037_relation_qualifier
Create Date: 2026-07-19
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0038_whatsapp_resend"
down_revision = "0037_relation_qualifier"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "whatsapp_message_logs",
        sa.Column("header_parameter_values", postgresql.JSONB(), nullable=True),
    )
    op.add_column(
        "whatsapp_message_logs",
        sa.Column("template_parameter_values", postgresql.JSONB(), nullable=True),
    )
    op.add_column(
        "whatsapp_message_logs",
        sa.Column(
            "is_explicit_resend",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.create_index(
        "uq_whatsapp_active_explicit_resend",
        "whatsapp_message_logs",
        ["recipient_id", "message_type"],
        unique=True,
        postgresql_where=sa.text(
            "is_explicit_resend = true "
            "AND status IN ('queued', 'processing', 'delivery_unknown')"
        ),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_whatsapp_active_explicit_resend",
        table_name="whatsapp_message_logs",
    )
    op.drop_column("whatsapp_message_logs", "is_explicit_resend")
    op.drop_column("whatsapp_message_logs", "template_parameter_values")
    op.drop_column("whatsapp_message_logs", "header_parameter_values")
