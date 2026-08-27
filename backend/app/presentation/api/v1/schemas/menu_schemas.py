"""Request and response contracts for the Menu and Meal Planner module."""

from __future__ import annotations

import uuid
from datetime import date as CalendarDate
from datetime import datetime

from pydantic import BaseModel, Field, field_validator


def _clean_text(value: str) -> str:
    return " ".join(value.strip().split())


class CreateMenuCategoryRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        cleaned = _clean_text(value)
        if not cleaned:
            raise ValueError("Category name is required")
        return cleaned


class UpdateMenuCategoryRequest(CreateMenuCategoryRequest):
    expected_updated_at: datetime


class CreateMenuDishRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    notes: str | None = Field(default=None, max_length=500)
    expected_category_updated_at: datetime

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        cleaned = _clean_text(value)
        if not cleaned:
            raise ValueError("Dish name is required")
        return cleaned

    @field_validator("notes")
    @classmethod
    def clean_notes(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = _clean_text(value)
        return cleaned or None


class UpdateMenuDishRequest(CreateMenuDishRequest):
    is_active: bool = True
    expected_updated_at: datetime


class GenerateMealPlanRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=150)
    trip_days: int = Field(..., ge=1, le=60)
    start_date: CalendarDate | None = None
    category_ids: list[uuid.UUID] | None = Field(default=None, max_length=100)
    expected_category_revisions: dict[uuid.UUID, datetime] = Field(
        default_factory=dict,
        max_length=100,
    )

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        cleaned = _clean_text(value)
        if not cleaned:
            raise ValueError("Plan name is required")
        return cleaned

    @field_validator("category_ids")
    @classmethod
    def unique_category_ids(
        cls,
        value: list[uuid.UUID] | None,
    ) -> list[uuid.UUID] | None:
        if value is None:
            return None
        return list(dict.fromkeys(value))


class RegenerateMealPlanRequest(BaseModel):
    category_ids: list[uuid.UUID] | None = Field(default=None, max_length=100)
    expected_updated_at: datetime
    expected_category_revisions: dict[uuid.UUID, datetime] = Field(
        default_factory=dict,
        max_length=100,
    )

    @field_validator("category_ids")
    @classmethod
    def unique_category_ids(
        cls,
        value: list[uuid.UUID] | None,
    ) -> list[uuid.UUID] | None:
        if value is None:
            return None
        return list(dict.fromkeys(value))


class UpdateMealPlanRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=150)
    start_date: CalendarDate | None = None
    expected_updated_at: datetime

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        cleaned = _clean_text(value)
        if not cleaned:
            raise ValueError("Plan name is required")
        return cleaned


class UpdateMealPlanEntryRequest(BaseModel):
    dish_id: uuid.UUID
    expected_updated_at: datetime
    expected_dish_updated_at: datetime
    expected_category_updated_at: datetime


class MenuRevisionRequest(BaseModel):
    expected_updated_at: datetime


class MenuDishRevisionRequest(MenuRevisionRequest):
    expected_category_updated_at: datetime


class MenuDishResponse(BaseModel):
    id: uuid.UUID
    category_id: uuid.UUID
    name: str
    notes: str | None = None
    is_active: bool
    sort_order: int
    created_at: datetime
    updated_at: datetime


class MenuCategoryResponse(BaseModel):
    id: uuid.UUID
    name: str
    sort_order: int
    dish_count: int
    active_dish_count: int
    dishes: list[MenuDishResponse] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class MealPlanEntryResponse(BaseModel):
    id: uuid.UUID
    day_number: int
    meal_type: str
    dish_id: uuid.UUID | None = None
    category_id: uuid.UUID | None = None
    dish_name: str
    category_name: str
    notes: str | None = None


class MealPlanDayResponse(BaseModel):
    day_number: int
    date: CalendarDate | None = None
    lunch: list[MealPlanEntryResponse] = Field(default_factory=list)
    dinner: list[MealPlanEntryResponse] = Field(default_factory=list)


class MealPlanResponse(BaseModel):
    id: uuid.UUID
    name: str
    trip_days: int
    start_date: CalendarDate | None = None
    selected_category_ids: list[uuid.UUID] = Field(default_factory=list)
    unique_dish_count: int
    days: list[MealPlanDayResponse] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class MenuWorkspaceResponse(BaseModel):
    categories: list[MenuCategoryResponse] = Field(default_factory=list)
    plans: list[MealPlanResponse] = Field(default_factory=list)
    total_dishes: int
    active_dishes: int
    max_trip_days_without_repeats: int
