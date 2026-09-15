"""Index collection-submitted phone discovery without rewriting stored contacts.

Revision ID: 0096_mobile_phone_lookup
Revises: 0095_mobile_fcm_delivery
"""

from alembic import op
import sqlalchemy as sa

revision = "0096_mobile_phone_lookup"
down_revision = "0095_mobile_fcm_delivery"
branch_labels = None
depends_on = None

_INDEX = "ix_passport_submissions_mobile_phone_lookup"


def upgrade() -> None:
    op.create_index(
        _INDEX,
        "passport_submissions",
        [sa.text(r"regexp_replace(coalesce(client_phone, ''), '\D', '', 'g')")],
        unique=False,
        postgresql_where=sa.text("client_reviewed_at IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(_INDEX, table_name="passport_submissions")
