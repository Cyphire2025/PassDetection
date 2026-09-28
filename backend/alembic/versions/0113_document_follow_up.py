"""Persist manual document follow-up flags without changing passport status."""

import sqlalchemy as sa

from alembic import op

revision = "0113_document_follow_up"
down_revision = "0112_passport_cover_edits"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.add_column(
        "passport_submissions",
        sa.Column("document_follow_up", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute("LOCK TABLE passport_submissions IN ACCESS EXCLUSIVE MODE")
    if op.get_bind().execute(sa.text(
        "SELECT EXISTS (SELECT 1 FROM passport_submissions WHERE document_follow_up)"
    )).scalar_one():
        raise RuntimeError("Clear document follow-up flags before downgrading to preserve follow-up work.")
    op.drop_column("passport_submissions", "document_follow_up")
