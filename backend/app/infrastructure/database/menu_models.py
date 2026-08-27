"""Database models for the reusable menu library and saved meal plans."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infrastructure.database.model_base import JSONB, Base


def _utcnow() -> datetime:
    return datetime.now(tz=UTC)


class MenuCategoryModel(Base):
    """One organization-scoped dish category such as Chicken or Paneer."""

    __tablename__ = "menu_categories"
    __table_args__ = (
        Index(
            "uq_menu_categories_platform_normalized_name",
            "normalized_name",
            unique=True,
            postgresql_where=text("agency_id IS NULL"),
            sqlite_where=text("agency_id IS NULL"),
        ),
        Index(
            "uq_menu_categories_agency_normalized_name",
            "agency_id",
            "normalized_name",
            unique=True,
            postgresql_where=text("agency_id IS NOT NULL"),
            sqlite_where=text("agency_id IS NOT NULL"),
        ),
        Index("ix_menu_categories_agency_sort", "agency_id", "sort_order"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    agency_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agencies.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(100), nullable=False)
    sort_order: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        onupdate=_utcnow,
        server_default=text("CURRENT_TIMESTAMP"),
    )

    dishes: Mapped[list[MenuDishModel]] = relationship(
        "MenuDishModel",
        back_populates="category",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by=lambda: (MenuDishModel.sort_order, MenuDishModel.name),
    )


class MenuDishModel(Base):
    """A reusable dish that may be selected by the meal planner."""

    __tablename__ = "menu_dishes"
    __table_args__ = (
        UniqueConstraint(
            "category_id",
            "normalized_name",
            name="uq_menu_dishes_category_normalized_name",
        ),
        Index("ix_menu_dishes_category_sort", "category_id", "sort_order"),
        Index("ix_menu_dishes_category_active", "category_id", "is_active"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    category_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("menu_categories.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(120), nullable=False)
    notes: Mapped[str | None] = mapped_column(String(500), nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
    )
    sort_order: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        onupdate=_utcnow,
        server_default=text("CURRENT_TIMESTAMP"),
    )

    category: Mapped[MenuCategoryModel] = relationship(
        "MenuCategoryModel",
        back_populates="dishes",
    )


class MealPlanModel(Base):
    """A saved lunch-and-dinner schedule for a multi-day trip."""

    __tablename__ = "meal_plans"
    __table_args__ = (
        CheckConstraint("trip_days BETWEEN 1 AND 60", name="ck_meal_plans_trip_days"),
        Index("ix_meal_plans_agency_created", "agency_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    agency_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agencies.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    trip_days: Mapped[int] = mapped_column(Integer, nullable=False)
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    selected_category_ids: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default=text("'[]'"),
    )
    generation_seed: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        onupdate=_utcnow,
        server_default=text("CURRENT_TIMESTAMP"),
    )

    entries: Mapped[list[MealPlanEntryModel]] = relationship(
        "MealPlanEntryModel",
        back_populates="plan",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by=lambda: (
            MealPlanEntryModel.day_number,
            MealPlanEntryModel.meal_type,
            MealPlanEntryModel.category_name,
        ),
    )


class MealPlanEntryModel(Base):
    """One category dish in a lunch or dinner, with readable snapshots."""

    __tablename__ = "meal_plan_entries"
    __table_args__ = (
        UniqueConstraint(
            "plan_id",
            "day_number",
            "meal_type",
            "category_id",
            name="uq_meal_plan_entries_plan_day_meal_category",
        ),
        CheckConstraint("day_number >= 1", name="ck_meal_plan_entries_day_number"),
        CheckConstraint(
            "meal_type IN ('lunch', 'dinner')",
            name="ck_meal_plan_entries_meal_type",
        ),
        Index("ix_meal_plan_entries_plan_day", "plan_id", "day_number"),
        Index("ix_meal_plan_entries_plan_dish", "plan_id", "dish_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    plan_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("meal_plans.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    day_number: Mapped[int] = mapped_column(Integer, nullable=False)
    meal_type: Mapped[str] = mapped_column(String(16), nullable=False)
    dish_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("menu_dishes.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    category_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("menu_categories.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    dish_name: Mapped[str] = mapped_column(String(120), nullable=False)
    category_name: Mapped[str] = mapped_column(String(100), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        onupdate=_utcnow,
        server_default=text("CURRENT_TIMESTAMP"),
    )

    plan: Mapped[MealPlanModel] = relationship(
        "MealPlanModel",
        back_populates="entries",
    )
