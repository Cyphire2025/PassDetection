"""Optional company logos and group header images in private object storage."""

import sqlalchemy as sa

from alembic import op

revision = "0141_workspace_branding"
down_revision = "0140_document_update_context"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.add_column("client_organizations", sa.Column("logo_image_key", sa.String(512), nullable=True))
    op.add_column("client_groups", sa.Column("banner_image_key", sa.String(512), nullable=True))


def downgrade() -> None:
    op.drop_column("client_groups", "banner_image_key")
    op.drop_column("client_organizations", "logo_image_key")
