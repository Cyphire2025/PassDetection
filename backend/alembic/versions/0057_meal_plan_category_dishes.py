"""Allow every meal to contain one dish from each selected category.

Revision ID: 0057_meal_categories
Revises: 0056_menu_planner
Create Date: 2026-07-26
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0057_meal_categories"
down_revision = "0056_menu_planner"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint(
        "uq_meal_plan_entries_plan_day_meal",
        "meal_plan_entries",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_meal_plan_entries_plan_day_meal_category",
        "meal_plan_entries",
        ["plan_id", "day_number", "meal_type", "category_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_meal_plan_entries_plan_day_meal_category",
        "meal_plan_entries",
        type_="unique",
    )
    # The former schema can keep only one category dish in each meal.
    op.execute(
        sa.text(
            """
            DELETE FROM meal_plan_entries
            WHERE id IN (
                SELECT id
                FROM (
                    SELECT
                        id,
                        ROW_NUMBER() OVER (
                            PARTITION BY plan_id, day_number, meal_type
                            ORDER BY category_name, id
                        ) AS row_number
                    FROM meal_plan_entries
                ) ranked
                WHERE ranked.row_number > 1
            )
            """
        )
    )
    op.create_unique_constraint(
        "uq_meal_plan_entries_plan_day_meal",
        "meal_plan_entries",
        ["plan_id", "day_number", "meal_type"],
    )
