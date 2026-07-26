from __future__ import annotations

import uuid

import pytest

from app.application.use_cases.menu.meal_plan_generator import (
    InsufficientUniqueDishesError,
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


def test_generated_plan_never_repeats_a_dish() -> None:
    chicken = uuid.uuid4()
    paneer = uuid.uuid4()
    fish = uuid.uuid4()
    dishes = [
        *[_dish(chicken, "Chicken", number) for number in range(1, 5)],
        *[_dish(paneer, "Paneer", number) for number in range(1, 5)],
        *[_dish(fish, "Fish", number) for number in range(1, 5)],
    ]

    assignments = generate_balanced_meal_assignments(dishes, trip_days=5, seed=42)

    assert len(assignments) == 10
    assert len({assignment.dish.id for assignment in assignments}) == 10
    assert {assignment.meal_type for assignment in assignments} == {"lunch", "dinner"}


def test_lunch_and_dinner_use_different_categories_when_possible() -> None:
    chicken = uuid.uuid4()
    paneer = uuid.uuid4()
    dishes = [
        *[_dish(chicken, "Chicken", number) for number in range(1, 5)],
        *[_dish(paneer, "Paneer", number) for number in range(1, 5)],
    ]

    assignments = generate_balanced_meal_assignments(dishes, trip_days=4, seed=7)

    for day_number in range(1, 5):
        day = [assignment for assignment in assignments if assignment.day_number == day_number]
        assert day[0].dish.category_id != day[1].dish.category_id


def test_generation_is_repeatable_for_a_saved_seed() -> None:
    category_id = uuid.uuid4()
    dishes = [_dish(category_id, "Vegetarian", number) for number in range(1, 7)]

    first = generate_balanced_meal_assignments(dishes, trip_days=3, seed=987)
    second = generate_balanced_meal_assignments(dishes, trip_days=3, seed=987)

    assert [assignment.dish.id for assignment in first] == [
        assignment.dish.id for assignment in second
    ]


def test_generation_fails_instead_of_repeating_when_library_is_too_small() -> None:
    category_id = uuid.uuid4()
    dishes = [_dish(category_id, "Paneer", number) for number in range(1, 4)]

    with pytest.raises(InsufficientUniqueDishesError) as error:
        generate_balanced_meal_assignments(dishes, trip_days=2, seed=1)

    assert error.value.required == 4
    assert error.value.available == 3
    assert error.value.missing == 1
