"""Tenant-scoped menu and meal-plan reads and duplicate-name checks."""

from __future__ import annotations

import uuid

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.infrastructure.database.menu_models import MealPlanModel, MenuCategoryModel, MenuDishModel

from .menu_common import _category_scope, _plan_scope


async def _get_category(
    session: AsyncSession,
    category_id: uuid.UUID,
    agency_id: uuid.UUID | None,
    *,
    include_dishes: bool = False,
    lock: bool = False,
) -> MenuCategoryModel:
    statement = select(MenuCategoryModel).where(
        MenuCategoryModel.id == category_id,
        _category_scope(MenuCategoryModel, agency_id),
    )
    if include_dishes:
        statement = statement.options(selectinload(MenuCategoryModel.dishes))
    if lock:
        statement = statement.with_for_update().execution_options(populate_existing=True)
    result = await session.execute(statement)
    category = result.scalar_one_or_none()
    if category is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Menu category not found",
        )
    return category


async def _get_dish(
    session: AsyncSession,
    dish_id: uuid.UUID,
    agency_id: uuid.UUID | None,
    *,
    lock: bool = False,
) -> tuple[MenuDishModel, MenuCategoryModel]:
    statement = (
        select(MenuDishModel, MenuCategoryModel)
        .join(MenuCategoryModel, MenuCategoryModel.id == MenuDishModel.category_id)
        .where(
            MenuDishModel.id == dish_id,
            _category_scope(MenuCategoryModel, agency_id),
        )
    )
    if lock:
        statement = statement.with_for_update().execution_options(populate_existing=True)
    result = await session.execute(statement)
    row = result.one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Menu dish not found",
        )
    return row[0], row[1]


async def _get_plan(
    session: AsyncSession,
    plan_id: uuid.UUID,
    agency_id: uuid.UUID | None,
    *,
    include_entries: bool = False,
    lock: bool = False,
) -> MealPlanModel:
    statement = select(MealPlanModel).where(
        MealPlanModel.id == plan_id,
        _plan_scope(MealPlanModel, agency_id),
    )
    if include_entries:
        statement = statement.options(selectinload(MealPlanModel.entries))
    if lock:
        statement = statement.with_for_update().execution_options(populate_existing=True)
    result = await session.execute(statement)
    plan = result.scalar_one_or_none()
    if plan is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Meal plan not found",
        )
    return plan


async def _ensure_category_name_available(
    session: AsyncSession,
    *,
    agency_id: uuid.UUID | None,
    normalized_name: str,
    exclude_id: uuid.UUID | None = None,
) -> None:
    statement = select(MenuCategoryModel.id).where(
        _category_scope(MenuCategoryModel, agency_id),
        MenuCategoryModel.normalized_name == normalized_name,
    )
    if exclude_id is not None:
        statement = statement.where(MenuCategoryModel.id != exclude_id)
    if (await session.execute(statement)).scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A category with this name already exists",
        )


async def _ensure_dish_name_available(
    session: AsyncSession,
    *,
    category_id: uuid.UUID,
    normalized_name: str,
    exclude_id: uuid.UUID | None = None,
) -> None:
    statement = select(MenuDishModel.id).where(
        MenuDishModel.category_id == category_id,
        MenuDishModel.normalized_name == normalized_name,
    )
    if exclude_id is not None:
        statement = statement.where(MenuDishModel.id != exclude_id)
    if (await session.execute(statement)).scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This dish already exists in the category",
        )
