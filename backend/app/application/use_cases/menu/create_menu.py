"""Flush-only additive menu creation shared by website and MCP transports.

The fixed support bundle supplies existing selection, revision and generator
rules. Callers authorize scope, validate typed requests, audit and own commit.
No existing plan entries, dishes or categories are replaced or removed.
"""

from __future__ import annotations

import secrets
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.menu_models import (
    MealPlanEntryModel,
    MealPlanModel,
    MenuCategoryModel,
    MenuDishModel,
)


@dataclass(frozen=True, slots=True)
class MenuCreationSupport:
    _normalized_name: Callable[..., Any]
    _ensure_category_name_available: Callable[..., Any]
    _category_scope: Callable[..., Any]
    _get_category: Callable[..., Any]
    _require_current_revision: Callable[..., Any]
    _ensure_dish_name_available: Callable[..., Any]
    _utcnow: Callable[..., Any]
    _planner_categories: Callable[..., Any]
    _require_current_category_revisions: Callable[..., Any]
    _generate_or_422: Callable[..., Any]
    _meal_plan_entries: Callable[..., Any]


async def create_category(
    session: AsyncSession,
    *,
    support: MenuCreationSupport,
    agency_id: uuid.UUID | None,
    actor_id: uuid.UUID,
    body: Any,
) -> MenuCategoryModel:
    normalized_name = support._normalized_name(body.name)
    await support._ensure_category_name_available(
        session,
        agency_id=agency_id,
        normalized_name=normalized_name,
    )

    sort_order = (
        int(
            (
                await session.execute(
                    select(func.coalesce(func.max(MenuCategoryModel.sort_order), -1)).where(
                        support._category_scope(MenuCategoryModel, agency_id)
                    )
                )
            ).scalar_one()
        )
        + 1
    )
    category = MenuCategoryModel(
        agency_id=agency_id,
        name=body.name,
        normalized_name=normalized_name,
        sort_order=sort_order,
        created_by_user_id=actor_id,
    )
    session.add(category)
    await session.flush()
    return category


async def create_dish(
    session: AsyncSession,
    *,
    support: MenuCreationSupport,
    agency_id: uuid.UUID | None,
    actor_id: uuid.UUID,
    body: Any,
    category_id: uuid.UUID,
) -> tuple[MenuDishModel, MenuCategoryModel]:
    category = await support._get_category(session, category_id, agency_id, lock=True)
    support._require_current_revision(
        actual=category.updated_at,
        expected=body.expected_category_updated_at,
        resource="menu category",
    )
    normalized_name = support._normalized_name(body.name)
    await support._ensure_dish_name_available(
        session,
        category_id=category.id,
        normalized_name=normalized_name,
    )
    sort_order = (
        int(
            (
                await session.execute(
                    select(func.coalesce(func.max(MenuDishModel.sort_order), -1)).where(
                        MenuDishModel.category_id == category.id
                    )
                )
            ).scalar_one()
        )
        + 1
    )
    dish = MenuDishModel(
        category_id=category.id,
        name=body.name,
        normalized_name=normalized_name,
        notes=body.notes,
        is_active=True,
        sort_order=sort_order,
        created_by_user_id=actor_id,
    )
    session.add(dish)
    category.updated_at = support._utcnow()
    await session.flush()
    return dish, category


async def create_plan(
    session: AsyncSession,
    *,
    support: MenuCreationSupport,
    agency_id: uuid.UUID | None,
    actor_id: uuid.UUID,
    body: Any,
) -> tuple[MealPlanModel, list[MealPlanEntryModel]]:
    planner_categories = await support._planner_categories(
        session,
        agency_id=agency_id,
        category_ids=body.category_ids,
        lock=True,
    )
    support._require_current_category_revisions(
        planner_categories,
        body.expected_category_revisions,
    )
    seed = secrets.randbelow(2**63 - 1)
    assignments = support._generate_or_422(
        planner_categories,
        trip_days=body.trip_days,
        seed=seed,
    )
    selected_category_ids = [str(category.id) for category in planner_categories]
    plan = MealPlanModel(
        agency_id=agency_id,
        name=body.name,
        trip_days=body.trip_days,
        start_date=body.start_date,
        selected_category_ids=selected_category_ids,
        generation_seed=seed,
        created_by_user_id=actor_id,
    )
    session.add(plan)
    await session.flush()
    entries = support._meal_plan_entries(plan.id, assignments)
    session.add_all(entries)
    await session.flush()
    return plan, entries
