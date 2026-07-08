"""Add deleted group retention metadata.

Revision ID: 0009_deleted_group_retention
Revises: 0008_group_trip_details
Create Date: 2026-07-04 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0009_deleted_group_retention"
down_revision = "0008_group_trip_details"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE group_status_enum ADD VALUE IF NOT EXISTS 'deleted'")
    op.add_column("client_groups", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "client_groups",
        sa.Column("deleted_passport_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "client_groups",
        sa.Column("deletion_retained_records", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("client_groups", "deletion_retained_records")
    op.drop_column("client_groups", "deleted_passport_count")
    op.drop_column("client_groups", "deleted_at")
