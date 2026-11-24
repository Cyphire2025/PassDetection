"""Current organization menu workspace read."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.domain.entities.entities import User
from app.infrastructure.database.menu_models import MealPlanModel, MenuCategoryModel
from app.infrastructure.database.session import get_db_session
from app.presentation.api.v1.schemas.menu_schemas import MenuWorkspaceResponse
from app.presentation.dependencies.auth import require_role

from .menu_common import MENU_ROLES, _agency_scope, _category_scope, _plan_scope
from .menu_presenters import _category_response, _plan_response

router = APIRouter()


@router.get(
    "",
    response_model=MenuWorkspaceResponse,
    summary="Get the current organization's menu library and saved meal plans",
)
async def get_menu_workspace(
    current_user: User = Depends(require_role(MENU_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> MenuWorkspaceResponse:
    agency_id = _agency_scope(current_user)
    category_result = await session.execute(
        select(MenuCategoryModel)
        .where(_category_scope(MenuCategoryModel, agency_id))
        .options(selectinload(MenuCategoryModel.dishes))
        .order_by(MenuCategoryModel.sort_order, func.lower(MenuCategoryModel.name))
    )
    categories = list(category_result.scalars().unique().all())

    plan_result = await session.execute(
        select(MealPlanModel)
        .where(_plan_scope(MealPlanModel, agency_id))
        .options(selectinload(MealPlanModel.entries))
        .order_by(MealPlanModel.created_at.desc())
    )
    plans = list(plan_result.scalars().unique().all())

    total_dishes = sum(len(category.dishes) for category in categories)
    active_dishes = sum(1 for category in categories for dish in category.dishes if dish.is_active)
    active_category_counts = [
        sum(1 for dish in category.dishes if dish.is_active)
        for category in categories
        if any(dish.is_active for dish in category.dishes)
    ]
    return MenuWorkspaceResponse(
        categories=[_category_response(category) for category in categories],
        plans=[_plan_response(plan, list(plan.entries)) for plan in plans],
        total_dishes=total_dishes,
        active_dishes=active_dishes,
        max_trip_days_without_repeats=(
            min(active_category_counts) // 2 if active_category_counts else 0
        ),
    )
