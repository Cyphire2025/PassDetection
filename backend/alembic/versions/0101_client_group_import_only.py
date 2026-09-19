"""Persist import-only client groups.

Revision ID: 0101_client_group_import_only
Revises: 0100_whatsapp_group_archive
"""

from alembic import op
import sqlalchemy as sa

revision = "0101_client_group_import_only"
down_revision = "0100_whatsapp_group_archive"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "client_groups",
        sa.Column("import_only", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    # Dropping the mode would expose internal roster tokens as public forms.
    raise RuntimeError("Import-only groups require schema0101; downgrade refused")
