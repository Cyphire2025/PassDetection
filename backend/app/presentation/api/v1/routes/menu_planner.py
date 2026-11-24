"""Current category selection and saved meal-entry construction."""

from __future__ import annotations

import uuid

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.application.use_cases.menu.meal_plan_generator import (
    InsufficientCategoryDishesError,
    MealSlotAssignment,
    PlannerCategory,
    PlannerDish,
    generate_balanced_meal_assignments,
)
from app.infrastructure.database.menu_models import MealPlanEntryModel, MenuCategoryModel

from .menu_common import _category_scope


async def _planner_categories(
    session: AsyncSession,
    *,
    agency_id: uuid.UUID | None,
    category_ids: list[uuid.UUID] | None,
    lock: bool = False,
) -> list[PlannerCategory]:
    if category_ids is not None and not category_ids:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Select at least one category",
        )

    statement = (
        select(MenuCategoryModel)
        .where(_category_scope(MenuCategoryModel, agency_id))
        .options(selectinload(MenuCategoryModel.dishes))
        .order_by(MenuCategoryModel.sort_order, func.lower(MenuCategoryModel.name))
    )
    if category_ids is not None:
        statement = statement.where(MenuCategoryModel.id.in_(category_ids))
    if lock:
        statement = statement.with_for_update().execution_options(populate_existing=True)

    category_result = await session.execute(statement)
    categories = list(category_result.scalars().unique().all())
    if category_ids is not None:
        categories_by_id = {category.id: category for category in categories}
        if set(categories_by_id) != set(category_ids):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="One or more selected categories are unavailable",
            )
        categories = [categories_by_id[category_id] for category_id in category_ids]

    planner_categories: list[PlannerCategory] = []
    for category in categories:
        active_dishes = sorted(
            (dish for dish in category.dishes if dish.is_active),
            key=lambda dish: (
                dish.sort_order,
                dish.name.casefold(),
                str(dish.id),
            ),
        )
        if category_ids is None and not active_dishes:
            continue
        planner_categories.append(
            PlannerCategory(
                id=category.id,
                name=category.name,
                updated_at=category.updated_at,
                dishes=tuple(
                    PlannerDish(
                        id=dish.id,
                        category_id=category.id,
                        name=dish.name,
                        category_name=category.name,
                        sort_order=dish.sort_order,
                    )
                    for dish in active_dishes
                ),
            )
        )

    if not planner_categories:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Select at least one category with active dishes",
        )
    return planner_categories


def _generate_or_422(
    planner_categories: list[PlannerCategory],
    *,
    trip_days: int,
    seed: int,
) -> list[MealSlotAssignment]:
    try:
        return generate_balanced_meal_assignments(
            planner_categories,
            trip_days=trip_days,
            seed=seed,
        )
    except InsufficientCategoryDishesError as exc:
        shortages = "; ".join(
            (
                f"{shortage.category_name}: add {shortage.missing} "
                f"dish{'es' if shortage.missing != 1 else ''}"
            )
            for shortage in exc.shortages
        )
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                f"Each selected category needs {exc.required_per_category} active "
                f"dishes for a {trip_days}-day lunch and dinner plan. {shortages}."
            ),
        ) from exc


def _meal_plan_entries(
    plan_id: uuid.UUID,
    assignments: list[MealSlotAssignment],
) -> list[MealPlanEntryModel]:
    return [
        MealPlanEntryModel(
            plan_id=plan_id,
            day_number=assignment.day_number,
            meal_type=assignment.meal_type,
            dish_id=assignment.dish.id,
            category_id=assignment.dish.category_id,
            dish_name=assignment.dish.name,
            category_name=assignment.dish.category_name,
        )
        for assignment in assignments
    ]
