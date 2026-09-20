"""Freeze the selected language on broadcast message snapshots.

Revision ID: 0103_whatsapp_template_language
Revises: 0102_public_upload_contact_otp
"""

import sqlalchemy as sa
from alembic import op

revision = "0103_whatsapp_template_language"
down_revision = "0102_public_upload_contact_otp"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("whatsapp_message_logs", sa.Column("template_language", sa.String(16), nullable=True))


def downgrade() -> None:
    op.drop_column("whatsapp_message_logs", "template_language")
