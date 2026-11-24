"""Menu library and saved-plan response projection."""

from __future__ import annotations

import uuid
from datetime import timedelta

from app.infrastructure.database.menu_models import (
    MealPlanEntryModel,
    MealPlanModel,
    MenuCategoryModel,
    MenuDishModel,
)
from app.presentation.api.v1.schemas.menu_schemas import (
    MealPlanDayResponse,
    MealPlanEntryResponse,
    MealPlanResponse,
    MenuCategoryResponse,
    MenuDishResponse,
)


def _dish_response(dish: MenuDishModel) -> MenuDishResponse:
    return MenuDishResponse(
        id=dish.id,
        category_id=dish.category_id,
        name=dish.name,
        notes=dish.notes,
        is_active=dish.is_active,
        sort_order=dish.sort_order,
        created_at=dish.created_at,
        updated_at=dish.updated_at,
    )


def _category_response(
    category: MenuCategoryModel,
    *,
    dishes: list[MenuDishModel] | None = None,
) -> MenuCategoryResponse:
    sorted_dishes = sorted(
        list(category.dishes) if dishes is None else dishes,
        key=lambda dish: (dish.sort_order, dish.name.casefold()),
    )
    return MenuCategoryResponse(
        id=category.id,
        name=category.name,
        sort_order=category.sort_order,
        dish_count=len(sorted_dishes),
        active_dish_count=sum(1 for dish in sorted_dishes if dish.is_active),
        dishes=[_dish_response(dish) for dish in sorted_dishes],
        created_at=category.created_at,
        updated_at=category.updated_at,
    )


def _entry_response(entry: MealPlanEntryModel) -> MealPlanEntryResponse:
    return MealPlanEntryResponse(
        id=entry.id,
        day_number=entry.day_number,
        meal_type=entry.meal_type,
        dish_id=entry.dish_id,
        category_id=entry.category_id,
        dish_name=entry.dish_name,
        category_name=entry.category_name,
        notes=entry.notes,
    )


def _plan_response(
    plan: MealPlanModel,
    entries: list[MealPlanEntryModel],
) -> MealPlanResponse:
    category_order = {
        str(category_id): index for index, category_id in enumerate(plan.selected_category_ids)
    }
    by_day: dict[int, dict[str, list[MealPlanEntryModel]]] = {}
    for entry in entries:
        by_day.setdefault(entry.day_number, {}).setdefault(entry.meal_type, []).append(entry)

    days: list[MealPlanDayResponse] = []
    for day_number in range(1, plan.trip_days + 1):
        day_entries = by_day.get(day_number, {})
        lunch = day_entries.get("lunch", [])
        dinner = day_entries.get("dinner", [])
        if not lunch or not dinner:
            raise RuntimeError(f"Meal plan {plan.id} is missing day {day_number} entries")

        def entry_sort_key(entry: MealPlanEntryModel) -> tuple[int, str, str]:
            category_id = str(entry.category_id) if entry.category_id else ""
            return (
                category_order.get(category_id, len(category_order)),
                entry.category_name.casefold(),
                str(entry.id),
            )

        days.append(
            MealPlanDayResponse(
                day_number=day_number,
                date=(
                    plan.start_date + timedelta(days=day_number - 1) if plan.start_date else None
                ),
                lunch=[_entry_response(entry) for entry in sorted(lunch, key=entry_sort_key)],
                dinner=[_entry_response(entry) for entry in sorted(dinner, key=entry_sort_key)],
            )
        )

    return MealPlanResponse(
        id=plan.id,
        name=plan.name,
        trip_days=plan.trip_days,
        start_date=plan.start_date,
        selected_category_ids=[
            uuid.UUID(str(category_id)) for category_id in plan.selected_category_ids
        ],
        unique_dish_count=len(entries),
        days=days,
        created_at=plan.created_at,
        updated_at=plan.updated_at,
    )
