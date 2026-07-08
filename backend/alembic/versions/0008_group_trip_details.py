"""Add trip details to client groups.

Revision ID: 0008_group_trip_details
Revises: 0007_manager_group_access
Create Date: 2026-07-04 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0008_group_trip_details"
down_revision = "0007_manager_group_access"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("client_groups", sa.Column("destination", sa.String(length=255), nullable=True))
    op.add_column("client_groups", sa.Column("travel_date", sa.Date(), nullable=True))
    op.add_column("client_groups", sa.Column("return_date", sa.Date(), nullable=True))
    op.add_column("client_groups", sa.Column("package_name", sa.String(length=255), nullable=True))
    op.add_column("client_groups", sa.Column("notes", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("client_groups", "notes")
    op.drop_column("client_groups", "package_name")
    op.drop_column("client_groups", "return_date")
    op.drop_column("client_groups", "travel_date")
    op.drop_column("client_groups", "destination")
