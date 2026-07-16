"""Add WhatsApp status transition timestamps.

Revision ID: 0032_whatsapp_status_time
Revises: 0031_whatsapp_batches
Create Date: 2026-07-17
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0032_whatsapp_status_time"
down_revision = "0031_whatsapp_batches"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "whatsapp_message_logs",
        sa.Column("status_updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        "UPDATE whatsapp_message_logs "
        "SET status_updated_at = created_at "
        "WHERE status_updated_at IS NULL"
    )
    op.alter_column("whatsapp_message_logs", "status_updated_at", nullable=False)


def downgrade() -> None:
    op.drop_column("whatsapp_message_logs", "status_updated_at")
