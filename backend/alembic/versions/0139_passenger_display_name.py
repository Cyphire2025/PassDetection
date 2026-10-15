"""Optional office display labels independent of passport/contact identity."""

import sqlalchemy as sa

from alembic import op

revision = "0139_passenger_display_name"
down_revision = "0138_verified_portal_lookup"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.add_column("passport_submissions", sa.Column("display_name", sa.String(255), nullable=True))


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.drop_column("passport_submissions", "display_name")
