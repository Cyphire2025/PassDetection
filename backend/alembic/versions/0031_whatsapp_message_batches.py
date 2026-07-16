"""Add WhatsApp message batch tracking.

Revision ID: 0031_whatsapp_batches
Revises: 0030_whatsapp_metadata
Create Date: 2026-07-17
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0031_whatsapp_batches"
down_revision = "0030_whatsapp_metadata"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "whatsapp_message_logs",
        sa.Column("batch_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_index(
        "ix_whatsapp_message_logs_batch_id",
        "whatsapp_message_logs",
        ["batch_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_whatsapp_message_logs_batch_id", table_name="whatsapp_message_logs")
    op.drop_column("whatsapp_message_logs", "batch_id")
