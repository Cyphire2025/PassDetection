"""Optional private group workspace backgrounds, preserving existing branding."""

import sqlalchemy as sa

from alembic import op

revision = "0142_group_background"
down_revision = "0141_workspace_branding"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.add_column("client_groups", sa.Column("background_image_key", sa.String(512), nullable=True))


def downgrade() -> None:
    if op.get_bind().execute(sa.text(
        "SELECT 1 FROM client_groups WHERE background_image_key IS NOT NULL LIMIT 1"
    )).first():
        raise RuntimeError("Remove group backgrounds before downgrading; stored image references must be preserved")
    op.drop_column("client_groups", "background_image_key")
