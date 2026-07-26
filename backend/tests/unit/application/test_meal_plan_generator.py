from __future__ import annotations

import uuid

import pytest

from app.application.use_cases.menu.meal_plan_generator import (
    InsufficientCategoryDishesError,
    PlannerCategory,
    PlannerDish,
    generate_balanced_meal_assignments,
)


def _dish(category_id: uuid.UUID, category_name: str, number: int) -> PlannerDish:
    return PlannerDish(
        id=uuid.uuid5(category_id, str(number)),
        category_id=category_id,
        name=f"{category_name} dish {number}",
        category_name=category_name,
        sort_order=number,
    )


def _category(name: str, dish_count: int) -> PlannerCategory:
    category_id = uuid.uuid4()
    return PlannerCategory(
        id=category_id,
        name=name,
        dishes=tuple(_dish(category_id, name, number) for number in range(1, dish_count + 1)),
    )


def test_every_meal_contains_one_unique_dish_from_every_selected_category() -> None:
    categories = [
        _category("Chicken", 6),
        _category("Paneer", 6),
        _category("Fish", 6),
        _category("Dal", 6),
    ]

    assignments = generate_balanced_meal_assignments(
        categories,
        trip_days=3,
        seed=42,
    )

    assert len(assignments) == 24
    assert len({assignment.dish.id for assignment in assignments}) == 24
    for day_number in range(1, 4):
        for meal_type in ("lunch", "dinner"):
            meal = [
                assignment
                for assignment in assignments
                if assignment.day_number == day_number and assignment.meal_type == meal_type
            ]
            assert [assignment.dish.category_id for assignment in meal] == [
                category.id for category in categories
            ]


def test_generation_is_repeatable_for_a_saved_seed() -> None:
    categories = [_category("Vegetarian", 6)]

    first = generate_balanced_meal_assignments(categories, trip_days=3, seed=987)
    second = generate_balanced_meal_assignments(categories, trip_days=3, seed=987)

    assert [assignment.dish.id for assignment in first] == [
        assignment.dish.id for assignment in second
    ]


def test_generation_reports_each_selected_category_that_is_too_small() -> None:
    chicken = _category("Chicken", 3)
    paneer = _category("Paneer", 4)

    with pytest.raises(InsufficientCategoryDishesError) as error:
        generate_balanced_meal_assignments(
            [chicken, paneer],
            trip_days=2,
            seed=1,
        )

    assert error.value.required_per_category == 4
    assert len(error.value.shortages) == 1
    assert error.value.shortages[0].category_name == "Chicken"
    assert error.value.shortages[0].available == 3
    assert error.value.shortages[0].missing == 1
