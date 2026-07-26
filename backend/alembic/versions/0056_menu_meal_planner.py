"""Add the reusable menu library and saved non-repeating meal plans.

Revision ID: 0056_menu_planner
Revises: 0055_image_library
Create Date: 2026-07-26
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0056_menu_planner"
down_revision = "0055_image_library"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "menu_categories",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agency_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("normalized_name", sa.String(length=100), nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["agency_id"],
            ["agencies.id"],
            name="fk_menu_categories_agency",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name="fk_menu_categories_created_by",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_menu_categories"),
    )
    op.create_index(
        "ix_menu_categories_agency_id",
        "menu_categories",
        ["agency_id"],
        unique=False,
    )
    op.create_index(
        "ix_menu_categories_created_by_user_id",
        "menu_categories",
        ["created_by_user_id"],
        unique=False,
    )
    op.create_index(
        "ix_menu_categories_agency_sort",
        "menu_categories",
        ["agency_id", "sort_order"],
        unique=False,
    )
    op.create_index(
        "uq_menu_categories_platform_normalized_name",
        "menu_categories",
        ["normalized_name"],
        unique=True,
        postgresql_where=sa.text("agency_id IS NULL"),
    )
    op.create_index(
        "uq_menu_categories_agency_normalized_name",
        "menu_categories",
        ["agency_id", "normalized_name"],
        unique=True,
        postgresql_where=sa.text("agency_id IS NOT NULL"),
    )

    op.create_table(
        "menu_dishes",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("category_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("normalized_name", sa.String(length=120), nullable=False),
        sa.Column("notes", sa.String(length=500), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["category_id"],
            ["menu_categories.id"],
            name="fk_menu_dishes_category",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name="fk_menu_dishes_created_by",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_menu_dishes"),
        sa.UniqueConstraint(
            "category_id",
            "normalized_name",
            name="uq_menu_dishes_category_normalized_name",
        ),
    )
    op.create_index(
        "ix_menu_dishes_category_id",
        "menu_dishes",
        ["category_id"],
        unique=False,
    )
    op.create_index(
        "ix_menu_dishes_created_by_user_id",
        "menu_dishes",
        ["created_by_user_id"],
        unique=False,
    )
    op.create_index(
        "ix_menu_dishes_category_sort",
        "menu_dishes",
        ["category_id", "sort_order"],
        unique=False,
    )
    op.create_index(
        "ix_menu_dishes_category_active",
        "menu_dishes",
        ["category_id", "is_active"],
        unique=False,
    )

    op.create_table(
        "meal_plans",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agency_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("name", sa.String(length=150), nullable=False),
        sa.Column("trip_days", sa.Integer(), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column(
            "selected_category_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("generation_seed", sa.BigInteger(), nullable=False),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "trip_days BETWEEN 1 AND 60",
            name="ck_meal_plans_trip_days",
        ),
        sa.ForeignKeyConstraint(
            ["agency_id"],
            ["agencies.id"],
            name="fk_meal_plans_agency",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name="fk_meal_plans_created_by",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_meal_plans"),
    )
    op.create_index(
        "ix_meal_plans_agency_id",
        "meal_plans",
        ["agency_id"],
        unique=False,
    )
    op.create_index(
        "ix_meal_plans_created_by_user_id",
        "meal_plans",
        ["created_by_user_id"],
        unique=False,
    )
    op.create_index(
        "ix_meal_plans_agency_created",
        "meal_plans",
        ["agency_id", "created_at"],
        unique=False,
    )

    op.create_table(
        "meal_plan_entries",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("plan_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("day_number", sa.Integer(), nullable=False),
        sa.Column("meal_type", sa.String(length=16), nullable=False),
        sa.Column("dish_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("category_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("dish_name", sa.String(length=120), nullable=False),
        sa.Column("category_name", sa.String(length=100), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "day_number >= 1",
            name="ck_meal_plan_entries_day_number",
        ),
        sa.CheckConstraint(
            "meal_type IN ('lunch', 'dinner')",
            name="ck_meal_plan_entries_meal_type",
        ),
        sa.ForeignKeyConstraint(
            ["category_id"],
            ["menu_categories.id"],
            name="fk_meal_plan_entries_category",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["dish_id"],
            ["menu_dishes.id"],
            name="fk_meal_plan_entries_dish",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["plan_id"],
            ["meal_plans.id"],
            name="fk_meal_plan_entries_plan",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_meal_plan_entries"),
        sa.UniqueConstraint(
            "plan_id",
            "day_number",
            "meal_type",
            name="uq_meal_plan_entries_plan_day_meal",
        ),
    )
    op.create_index(
        "ix_meal_plan_entries_plan_id",
        "meal_plan_entries",
        ["plan_id"],
        unique=False,
    )
    op.create_index(
        "ix_meal_plan_entries_dish_id",
        "meal_plan_entries",
        ["dish_id"],
        unique=False,
    )
    op.create_index(
        "ix_meal_plan_entries_category_id",
        "meal_plan_entries",
        ["category_id"],
        unique=False,
    )
    op.create_index(
        "ix_meal_plan_entries_plan_day",
        "meal_plan_entries",
        ["plan_id", "day_number"],
        unique=False,
    )
    op.create_index(
        "ix_meal_plan_entries_plan_dish",
        "meal_plan_entries",
        ["plan_id", "dish_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_table("meal_plan_entries")
    op.drop_table("meal_plans")
    op.drop_table("menu_dishes")
    op.drop_table("menu_categories")
