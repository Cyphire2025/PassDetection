"""Configurable traveller collection and passport cover images.

Revision ID: 0090_upload_configuration
Revises: 0089_revoke_legacy_refresh
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0090_upload_configuration"
down_revision = "0089_revoke_legacy_refresh"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("client_groups", sa.Column("upload_configuration", postgresql.JSONB(), nullable=True))
    op.add_column("passport_submissions", sa.Column("passport_cover_s3_key", sa.String(1024), nullable=True))
    op.add_column("passport_submissions", sa.Column("passport_back_cover_s3_key", sa.String(1024), nullable=True))


def downgrade() -> None:
    op.drop_column("passport_submissions", "passport_back_cover_s3_key")
    op.drop_column("passport_submissions", "passport_cover_s3_key")
    op.drop_column("client_groups", "upload_configuration")
