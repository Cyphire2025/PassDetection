"""Store imported staff attributes and the three passport document images.

Revision ID: 0027_staff_passport_docs
Revises: 0026_whatsapp_broadcasts
Create Date: 2026-07-15
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0027_staff_passport_docs"
down_revision = "0026_whatsapp_broadcasts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("passport_submissions", sa.Column("staff_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column("passport_submissions", sa.Column("passport_photo_s3_key", sa.String(length=512), nullable=True))
    op.add_column("passport_submissions", sa.Column("passport_back_s3_key", sa.String(length=512), nullable=True))


def downgrade() -> None:
    op.drop_column("passport_submissions", "passport_back_s3_key")
    op.drop_column("passport_submissions", "passport_photo_s3_key")
    op.drop_column("passport_submissions", "staff_metadata")
