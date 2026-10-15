"""Freeze document update scope separately from PDF delivery history."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0131_document_update_context"
down_revision = "0130_passenger_display_name"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.add_column("whatsapp_message_logs", sa.Column("document_update_context", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.drop_column("whatsapp_message_logs", "document_update_context")
