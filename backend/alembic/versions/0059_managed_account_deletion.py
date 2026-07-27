"""Mark history-backed managed accounts as deleted.

Revision ID: 0059_account_deletion
Revises: 0058_rooming_auto
Create Date: 2026-07-27
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0059_account_deletion"
down_revision = "0058_rooming_auto"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "deleted_at")
