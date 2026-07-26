"""Constraint-based generation of category-complete, non-repeating meal plans."""

from __future__ import annotations

import random
import uuid
from dataclasses import dataclass

MEAL_TYPES = ("lunch", "dinner")


@dataclass(frozen=True, slots=True)
class PlannerDish:
    id: uuid.UUID
    category_id: uuid.UUID
    name: str
    category_name: str
    sort_order: int = 0


@dataclass(frozen=True, slots=True)
class PlannerCategory:
    id: uuid.UUID
    name: str
    dishes: tuple[PlannerDish, ...]


@dataclass(frozen=True, slots=True)
class MealSlotAssignment:
    day_number: int
    meal_type: str
    dish: PlannerDish


@dataclass(frozen=True, slots=True)
class CategoryDishShortage:
    category_id: uuid.UUID
    category_name: str
    required: int
    available: int

    @property
    def missing(self) -> int:
        return max(0, self.required - self.available)


class InsufficientCategoryDishesError(ValueError):
    """Raised when any selected category cannot cover every meal slot."""

    def __init__(
        self,
        *,
        required_per_category: int,
        shortages: tuple[CategoryDishShortage, ...],
    ) -> None:
        self.required_per_category = required_per_category
        self.shortages = shortages
        detail = ", ".join(
            f"{shortage.category_name}: {shortage.available}/{shortage.required}"
            for shortage in shortages
        )
        super().__init__(
            "Every selected category needs "
            f"{required_per_category} unique dishes; insufficient inventory: {detail}."
        )


def generate_balanced_meal_assignments(
    categories: list[PlannerCategory],
    *,
    trip_days: int,
    seed: int,
) -> list[MealSlotAssignment]:
    """Put one unique dish from every selected category in every meal."""

    if trip_days < 1:
        raise ValueError("trip_days must be at least 1")
    if not categories:
        raise ValueError("at least one category must be selected")

    required_per_category = trip_days * len(MEAL_TYPES)
    unique_categories = {category.id: category for category in categories}
    if len(unique_categories) != len(categories):
        raise ValueError("selected categories must be unique")

    unique_dishes_by_category: dict[uuid.UUID, list[PlannerDish]] = {}
    shortages: list[CategoryDishShortage] = []
    for category in categories:
        unique_dishes = {
            dish.id: dish for dish in category.dishes if dish.category_id == category.id
        }
        category_dishes = sorted(
            unique_dishes.values(),
            key=lambda item: (
                item.sort_order,
                item.name.casefold(),
                str(item.id),
            ),
        )
        unique_dishes_by_category[category.id] = category_dishes
        if len(category_dishes) < required_per_category:
            shortages.append(
                CategoryDishShortage(
                    category_id=category.id,
                    category_name=category.name,
                    required=required_per_category,
                    available=len(category_dishes),
                )
            )

    if shortages:
        raise InsufficientCategoryDishesError(
            required_per_category=required_per_category,
            shortages=tuple(shortages),
        )

    rng = random.Random(seed)
    for category_dishes in unique_dishes_by_category.values():
        rng.shuffle(category_dishes)

    assignments: list[MealSlotAssignment] = []
    for day_number in range(1, trip_days + 1):
        for meal_type in MEAL_TYPES:
            for category in categories:
                dish = unique_dishes_by_category[category.id].pop()
                assignments.append(
                    MealSlotAssignment(
                        day_number=day_number,
                        meal_type=meal_type,
                        dish=dish,
                    )
                )

    return assignments
