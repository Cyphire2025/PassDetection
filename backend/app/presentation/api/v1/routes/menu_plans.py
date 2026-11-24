"""Saved non-repeating meal-plan creation, regeneration and metadata changes."""

from __future__ import annotations

import secrets
import uuid

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.use_cases.menu.create_menu import create_plan
from app.domain.entities.entities import User
from app.infrastructure.database.menu_models import MealPlanEntryModel
from app.infrastructure.database.session import get_db_session
from app.presentation.api.v1.schemas.menu_schemas import (
    GenerateMealPlanRequest,
    MealPlanResponse,
    MenuRevisionRequest,
    RegenerateMealPlanRequest,
    UpdateMealPlanRequest,
)
from app.presentation.dependencies.auth import require_role
from app.presentation.dependencies.csrf import require_cookie_csrf

from .menu_common import (
    MENU_ROLES,
    _agency_scope,
    _audit,
    _require_current_category_revisions,
    _require_current_revision,
    _utcnow,
)
from .menu_creation_support import menu_creation_support
from .menu_planner import _generate_or_422, _meal_plan_entries, _planner_categories
from .menu_presenters import _plan_response
from .menu_queries import _get_plan

router = APIRouter()


@router.post(
    "/plans/generate",
    response_model=MealPlanResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Generate and save a balanced lunch/dinner plan with no repeated dishes",
)
async def generate_meal_plan(
    body: GenerateMealPlanRequest,
    request: Request,
    current_user: User = Depends(require_role(MENU_ROLES)),
    session: AsyncSession = Depends(get_db_session),
    _csrf: None = Depends(require_cookie_csrf),
) -> MealPlanResponse:
    agency_id = _agency_scope(current_user)
    plan, entries = await create_plan(
        session,
        support=menu_creation_support(),
        agency_id=agency_id,
        actor_id=current_user.id,
        body=body,
    )
    await _audit(
        session,
        current_user,
        request,
        action="menu.meal_plan_generated",
        entity_type="meal_plan",
        entity_id=plan.id,
        metadata={
            "name": plan.name,
            "trip_days": plan.trip_days,
            "meal_count": len(entries),
        },
    )
    return _plan_response(plan, entries)


@router.post(
    "/plans/{plan_id}/regenerate",
    response_model=MealPlanResponse,
    summary="Replace a saved plan with a new non-repeating arrangement",
)
async def regenerate_meal_plan(
    plan_id: uuid.UUID,
    body: RegenerateMealPlanRequest,
    request: Request,
    current_user: User = Depends(require_role(MENU_ROLES)),
    session: AsyncSession = Depends(get_db_session),
    _csrf: None = Depends(require_cookie_csrf),
) -> MealPlanResponse:
    agency_id = _agency_scope(current_user)
    plan = await _get_plan(session, plan_id, agency_id, lock=True)
    _require_current_revision(
        actual=plan.updated_at,
        expected=body.expected_updated_at,
        resource="meal plan",
    )
    category_ids = body.category_ids
    if category_ids is None and plan.selected_category_ids:
        category_ids = [uuid.UUID(str(category_id)) for category_id in plan.selected_category_ids]

    planner_categories = await _planner_categories(
        session,
        agency_id=agency_id,
        category_ids=category_ids,
        lock=True,
    )
    _require_current_category_revisions(
        planner_categories,
        body.expected_category_revisions,
    )
    seed = secrets.randbelow(2**63 - 1)
    assignments = _generate_or_422(
        planner_categories,
        trip_days=plan.trip_days,
        seed=seed,
    )
    await session.execute(delete(MealPlanEntryModel).where(MealPlanEntryModel.plan_id == plan.id))
    entries = _meal_plan_entries(plan.id, assignments)
    session.add_all(entries)
    plan.generation_seed = seed
    plan.selected_category_ids = [str(category.id) for category in planner_categories]
    plan.updated_at = _utcnow()
    await session.flush()
    await _audit(
        session,
        current_user,
        request,
        action="menu.meal_plan_regenerated",
        entity_type="meal_plan",
        entity_id=plan.id,
        metadata={"name": plan.name, "trip_days": plan.trip_days},
    )
    return _plan_response(plan, entries)


@router.patch(
    "/plans/{plan_id}",
    response_model=MealPlanResponse,
    summary="Rename a meal plan or change its trip start date",
)
async def update_meal_plan(
    plan_id: uuid.UUID,
    body: UpdateMealPlanRequest,
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
    previous_name = plan.name
    plan.name = body.name
    plan.start_date = body.start_date
    plan.updated_at = _utcnow()
    await session.flush()
    await _audit(
        session,
        current_user,
        request,
        action="menu.meal_plan_updated",
        entity_type="meal_plan",
        entity_id=plan.id,
        metadata={"previous_name": previous_name, "name": plan.name},
    )
    return _plan_response(plan, list(plan.entries))


@router.delete(
    "/plans/{plan_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a saved meal plan",
)
async def delete_meal_plan(
    plan_id: uuid.UUID,
    body: MenuRevisionRequest,
    request: Request,
    current_user: User = Depends(require_role(MENU_ROLES)),
    session: AsyncSession = Depends(get_db_session),
    _csrf: None = Depends(require_cookie_csrf),
) -> Response:
    agency_id = _agency_scope(current_user)
    plan = await _get_plan(session, plan_id, agency_id, lock=True)
    _require_current_revision(
        actual=plan.updated_at,
        expected=body.expected_updated_at,
        resource="meal plan",
    )
    metadata = {"name": plan.name, "trip_days": plan.trip_days}
    await session.delete(plan)
    await session.flush()
    await _audit(
        session,
        current_user,
        request,
        action="menu.meal_plan_deleted",
        entity_type="meal_plan",
        entity_id=plan.id,
        metadata=metadata,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
