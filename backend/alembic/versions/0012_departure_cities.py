"""Add departure cities to groups and submissions.

Revision ID: 0012_departure_cities
Revises: 0011_coord_group_assign
Create Date: 2026-07-08
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0012_departure_cities"
down_revision = "0011_coord_group_assign"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "client_groups",
        sa.Column(
            "departure_cities",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.alter_column("client_groups", "departure_cities", server_default=None)
    op.add_column("passport_submissions", sa.Column("departure_city", sa.String(length=120), nullable=True))
    op.create_index(
        op.f("ix_passport_submissions_departure_city"),
        "passport_submissions",
        ["departure_city"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_passport_submissions_departure_city"), table_name="passport_submissions")
    op.drop_column("passport_submissions", "departure_city")
    op.drop_column("client_groups", "departure_cities")
