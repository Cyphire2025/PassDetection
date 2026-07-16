"""Add configurable client fields to upload links.

Revision ID: 0028_group_field_options
Revises: 0027_staff_passport_docs
Create Date: 2026-07-16
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0028_group_field_options"
down_revision = "0027_staff_passport_docs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for column_name in (
        "base_city_enabled",
        "nearest_international_airport_enabled",
        "staff_code_enabled",
        "meal_preference_enabled",
    ):
        op.add_column(
            "client_groups",
            sa.Column(column_name, sa.Boolean(), nullable=False, server_default=sa.false()),
        )

    # Preserve the previous behavior for links that already had configured
    # departure cities before the explicit option was introduced.
    op.execute(
        """
        UPDATE client_groups
        SET nearest_international_airport_enabled = TRUE
        WHERE departure_cities IS NOT NULL
          AND jsonb_array_length(departure_cities) > 0
        """
    )


def downgrade() -> None:
    op.drop_column("client_groups", "meal_preference_enabled")
    op.drop_column("client_groups", "staff_code_enabled")
    op.drop_column("client_groups", "nearest_international_airport_enabled")
    op.drop_column("client_groups", "base_city_enabled")
