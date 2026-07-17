"""Add per-group selfie requirement.

Revision ID: 0029_group_require_selfie
Revises: 0028_group_field_options
Create Date: 2026-07-16
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0029_group_require_selfie"
down_revision = "0028_group_field_options"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "client_groups",
        sa.Column("require_selfie", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("client_groups", "require_selfie")
