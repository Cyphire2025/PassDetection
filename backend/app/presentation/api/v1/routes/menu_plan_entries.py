"""Replace one saved dish while retaining category and no-repeat guarantees."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.entities import User
from app.infrastructure.database.session import get_db_session
from app.presentation.api.v1.schemas.menu_schemas import (
    MealPlanResponse,
    UpdateMealPlanEntryRequest,
)
from app.presentation.dependencies.auth import require_role
from app.presentation.dependencies.csrf import require_cookie_csrf

from .menu_common import MENU_ROLES, _agency_scope, _audit, _require_current_revision, _utcnow
from .menu_presenters import _plan_response
from .menu_queries import _get_dish, _get_plan

router = APIRouter()


@router.patch(
    "/plans/{plan_id}/entries/{entry_id}",
    response_model=MealPlanResponse,
    summary="Replace one meal while preserving the no-repeat guarantee",
)
async def update_meal_plan_entry(
    plan_id: uuid.UUID,
    entry_id: uuid.UUID,
    body: UpdateMealPlanEntryRequest,
    request: Request,
    current_user: User = Depends(require_role(MENU_ROLES)),
    session: AsyncSession = Depends(get_db_session),
    _csrf: None = Depends(require_cookie_csrf),
) -> MealPlanResponse:
    agency_id = _agency_scope(current_user)
    plan = await _get_plan(
        session,
        plan_id,
        agency_id,
        include_entries=True,
        lock=True,
    )
    _require_current_revision(
        actual=plan.updated_at,
        expected=body.expected_updated_at,
        resource="meal plan",
    )
    entry = next((item for item in plan.entries if item.id == entry_id), None)
    if entry is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Meal plan entry not found",
        )
    dish, category = await _get_dish(
        session,
        body.dish_id,
        agency_id,
        lock=True,
    )
    _require_current_revision(
        actual=dish.updated_at,
        expected=body.expected_dish_updated_at,
        resource="menu dish",
    )
    _require_current_revision(
        actual=category.updated_at,
        expected=body.expected_category_updated_at,
        resource="menu category",
    )
    if not dish.is_active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Inactive dishes cannot be added to a meal plan",
        )
    if entry.category_id is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The original category was removed, so this saved dish cannot be changed",
        )
    if dish.category_id != entry.category_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Choose another {entry.category_name} dish so every meal keeps "
                "one dish from each selected category"
            ),
        )

    duplicate = next(
        (item for item in plan.entries if item.id != entry.id and item.dish_id == dish.id),
        None,
    )
    if duplicate is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"{dish.name} is already used for day {duplicate.day_number} "
                f"{duplicate.meal_type}. Choose another dish."
            ),
        )

    previous_dish_name = entry.dish_name
    entry.dish_id = dish.id
    entry.category_id = category.id
    entry.dish_name = dish.name
    entry.category_name = category.name
    entry.notes = dish.notes
    entry.updated_at = _utcnow()
    plan.updated_at = _utcnow()
    await session.flush()
    await _audit(
        session,
        current_user,
        request,
        action="menu.meal_plan_entry_updated",
        entity_type="meal_plan",
        entity_id=plan.id,
        metadata={
            "day_number": entry.day_number,
            "meal_type": entry.meal_type,
            "previous_dish": previous_dish_name,
            "dish": dish.name,
        },
    )
    return _plan_response(plan, list(plan.entries))
