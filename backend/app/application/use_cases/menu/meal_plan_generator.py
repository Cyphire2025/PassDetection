"""Constraint-based generation of balanced, non-repeating trip meal plans."""

from __future__ import annotations

import random
import uuid
from collections import defaultdict
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
class MealSlotAssignment:
    day_number: int
    meal_type: str
    dish: PlannerDish


class InsufficientUniqueDishesError(ValueError):
    """Raised when a strict no-repeat plan cannot be produced."""

    def __init__(self, *, required: int, available: int) -> None:
        self.required = required
        self.available = available
        self.missing = max(0, required - available)
        super().__init__(
            f"{required} unique dishes are required, but only {available} are available."
        )


def generate_balanced_meal_assignments(
    dishes: list[PlannerDish],
    *,
    trip_days: int,
    seed: int,
) -> list[MealSlotAssignment]:
    """Assign lunch and dinner while never repeating a dish.

    Category usage is kept as even as available inventory allows. Dinner also
    avoids lunch's category on the same day whenever another category still has
    a dish available.
    """

    if trip_days < 1:
        raise ValueError("trip_days must be at least 1")

    required = trip_days * len(MEAL_TYPES)
    unique_dishes = {dish.id: dish for dish in dishes}
    if len(unique_dishes) < required:
        raise InsufficientUniqueDishesError(
            required=required,
            available=len(unique_dishes),
        )

    rng = random.Random(seed)
    dishes_by_category: dict[uuid.UUID, list[PlannerDish]] = defaultdict(list)
    for dish in sorted(
        unique_dishes.values(),
        key=lambda item: (
            item.category_name.casefold(),
            item.sort_order,
            item.name.casefold(),
            str(item.id),
        ),
    ):
        dishes_by_category[dish.category_id].append(dish)

    for category_dishes in dishes_by_category.values():
        rng.shuffle(category_dishes)

    category_usage = {category_id: 0 for category_id in dishes_by_category}
    assignments: list[MealSlotAssignment] = []
    previous_category_id: uuid.UUID | None = None

    for day_number in range(1, trip_days + 1):
        categories_used_today: set[uuid.UUID] = set()

        for meal_type in MEAL_TYPES:
            eligible = [
                category_id
                for category_id, category_dishes in dishes_by_category.items()
                if category_dishes
            ]

            different_today = [
                category_id for category_id in eligible if category_id not in categories_used_today
            ]
            if different_today:
                eligible = different_today

            different_from_previous = [
                category_id for category_id in eligible if category_id != previous_category_id
            ]
            if different_from_previous:
                eligible = different_from_previous

            lowest_usage = min(category_usage[category_id] for category_id in eligible)
            balanced = [
                category_id
                for category_id in eligible
                if category_usage[category_id] == lowest_usage
            ]
            category_id = rng.choice(sorted(balanced, key=str))
            dish = dishes_by_category[category_id].pop()

            assignments.append(
                MealSlotAssignment(
                    day_number=day_number,
                    meal_type=meal_type,
                    dish=dish,
                )
            )
            category_usage[category_id] += 1
            categories_used_today.add(category_id)
            previous_category_id = category_id

    return assignments
