"""Reusable dish library and strict non-repeating trip meal plans."""

from __future__ import annotations

import re
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.application.use_cases.menu.meal_plan_generator import (
    InsufficientCategoryDishesError,
    MealSlotAssignment,
    PlannerCategory,
    PlannerDish,
    generate_balanced_meal_assignments,
)
from app.domain.entities.entities import User, UserRole
from app.infrastructure.database.menu_models import (
    MealPlanEntryModel,
    MealPlanModel,
    MenuCategoryModel,
    MenuDishModel,
)
from app.infrastructure.database.session import get_db_session
from app.infrastructure.export.meal_plan_excel_exporter import (
    MealPlanExcelExporter,
    MealPlanExportEntry,
)
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.presentation.api.v1.schemas.menu_schemas import (
    CreateMenuCategoryRequest,
    CreateMenuDishRequest,
    GenerateMealPlanRequest,
    MealPlanDayResponse,
    MealPlanEntryResponse,
    MealPlanResponse,
    MenuCategoryResponse,
    MenuDishResponse,
    MenuWorkspaceResponse,
    RegenerateMealPlanRequest,
    UpdateMealPlanEntryRequest,
    UpdateMealPlanRequest,
    UpdateMenuCategoryRequest,
    UpdateMenuDishRequest,
)
from app.presentation.dependencies.auth import require_role
from app.presentation.dependencies.csrf import require_cookie_csrf
from app.presentation.security.client_ip import trusted_client_ip

router = APIRouter()

MENU_ROLES = [
    UserRole.SUPER_ADMIN,
    UserRole.AGENCY_ADMIN,
    UserRole.AGENCY_MANAGER,
    UserRole.AGENCY_STAFF,
]


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


@router.post(
    "/categories",
    response_model=MenuCategoryResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a dish category",
)
async def create_menu_category(
    body: CreateMenuCategoryRequest,
    request: Request,
    current_user: User = Depends(require_role(MENU_ROLES)),
    session: AsyncSession = Depends(get_db_session),
    _csrf: None = Depends(require_cookie_csrf),
) -> MenuCategoryResponse:
    agency_id = _agency_scope(current_user)
    normalized_name = _normalized_name(body.name)
    await _ensure_category_name_available(
        session,
        agency_id=agency_id,
        normalized_name=normalized_name,
    )

    sort_order = (
        int(
            (
                await session.execute(
                    select(func.coalesce(func.max(MenuCategoryModel.sort_order), -1)).where(
                        _category_scope(MenuCategoryModel, agency_id)
                    )
                )
            ).scalar_one()
        )
        + 1
    )
    category = MenuCategoryModel(
        agency_id=agency_id,
        name=body.name,
        normalized_name=normalized_name,
        sort_order=sort_order,
        created_by_user_id=current_user.id,
    )
    session.add(category)
    await session.flush()
    await _audit(
        session,
        current_user,
        request,
        action="menu.category_created",
        entity_type="menu_category",
        entity_id=category.id,
        metadata={"name": category.name},
    )
    return _category_response(category, dishes=[])


@router.patch(
    "/categories/{category_id}",
    response_model=MenuCategoryResponse,
    summary="Rename a dish category",
)
async def update_menu_category(
    category_id: uuid.UUID,
    body: UpdateMenuCategoryRequest,
    request: Request,
    current_user: User = Depends(require_role(MENU_ROLES)),
    session: AsyncSession = Depends(get_db_session),
    _csrf: None = Depends(require_cookie_csrf),
) -> MenuCategoryResponse:
    agency_id = _agency_scope(current_user)
    category = await _get_category(session, category_id, agency_id, include_dishes=True)
    normalized_name = _normalized_name(body.name)
    await _ensure_category_name_available(
        session,
        agency_id=agency_id,
        normalized_name=normalized_name,
        exclude_id=category.id,
    )
    previous_name = category.name
    category.name = body.name
    category.normalized_name = normalized_name
    category.updated_at = _utcnow()
    await session.flush()
    await _audit(
        session,
        current_user,
        request,
        action="menu.category_updated",
        entity_type="menu_category",
        entity_id=category.id,
        metadata={"previous_name": previous_name, "name": category.name},
    )
    return _category_response(category)


@router.delete(
    "/categories/{category_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a category and its dishes",
)
async def delete_menu_category(
    category_id: uuid.UUID,
    request: Request,
    current_user: User = Depends(require_role(MENU_ROLES)),
    session: AsyncSession = Depends(get_db_session),
    _csrf: None = Depends(require_cookie_csrf),
) -> Response:
    agency_id = _agency_scope(current_user)
    category = await _get_category(session, category_id, agency_id, include_dishes=True)
    metadata = {"name": category.name, "dish_count": len(category.dishes)}
    await session.delete(category)
    await session.flush()
    await _audit(
        session,
        current_user,
        request,
        action="menu.category_deleted",
        entity_type="menu_category",
        entity_id=category.id,
        metadata=metadata,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/categories/{category_id}/dishes",
    response_model=MenuDishResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add a dish to a category",
)
async def create_menu_dish(
    category_id: uuid.UUID,
    body: CreateMenuDishRequest,
    request: Request,
    current_user: User = Depends(require_role(MENU_ROLES)),
    session: AsyncSession = Depends(get_db_session),
    _csrf: None = Depends(require_cookie_csrf),
) -> MenuDishResponse:
    agency_id = _agency_scope(current_user)
    category = await _get_category(session, category_id, agency_id)
    normalized_name = _normalized_name(body.name)
    await _ensure_dish_name_available(
        session,
        category_id=category.id,
        normalized_name=normalized_name,
    )
    sort_order = (
        int(
            (
                await session.execute(
                    select(func.coalesce(func.max(MenuDishModel.sort_order), -1)).where(
                        MenuDishModel.category_id == category.id
                    )
                )
            ).scalar_one()
        )
        + 1
    )
    dish = MenuDishModel(
        category_id=category.id,
        name=body.name,
        normalized_name=normalized_name,
        notes=body.notes,
        is_active=True,
        sort_order=sort_order,
        created_by_user_id=current_user.id,
    )
    session.add(dish)
    await session.flush()
    await _audit(
        session,
        current_user,
        request,
        action="menu.dish_created",
        entity_type="menu_dish",
        entity_id=dish.id,
        metadata={"name": dish.name, "category": category.name},
    )
    return _dish_response(dish)


@router.patch(
    "/dishes/{dish_id}",
    response_model=MenuDishResponse,
    summary="Edit or activate/deactivate a dish",
)
async def update_menu_dish(
    dish_id: uuid.UUID,
    body: UpdateMenuDishRequest,
    request: Request,
    current_user: User = Depends(require_role(MENU_ROLES)),
    session: AsyncSession = Depends(get_db_session),
    _csrf: None = Depends(require_cookie_csrf),
) -> MenuDishResponse:
    agency_id = _agency_scope(current_user)
    dish, category = await _get_dish(session, dish_id, agency_id)
    normalized_name = _normalized_name(body.name)
    await _ensure_dish_name_available(
        session,
        category_id=category.id,
        normalized_name=normalized_name,
        exclude_id=dish.id,
    )
    previous_name = dish.name
    dish.name = body.name
    dish.normalized_name = normalized_name
    dish.notes = body.notes
    dish.is_active = body.is_active
    dish.updated_at = _utcnow()
    await session.flush()
    await _audit(
        session,
        current_user,
        request,
        action="menu.dish_updated",
        entity_type="menu_dish",
        entity_id=dish.id,
        metadata={
            "previous_name": previous_name,
            "name": dish.name,
            "category": category.name,
            "is_active": dish.is_active,
        },
    )
    return _dish_response(dish)


@router.delete(
    "/dishes/{dish_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a dish while preserving saved-plan snapshots",
)
async def delete_menu_dish(
    dish_id: uuid.UUID,
    request: Request,
    current_user: User = Depends(require_role(MENU_ROLES)),
    session: AsyncSession = Depends(get_db_session),
    _csrf: None = Depends(require_cookie_csrf),
) -> Response:
    agency_id = _agency_scope(current_user)
    dish, category = await _get_dish(session, dish_id, agency_id)
    metadata = {"name": dish.name, "category": category.name}
    await session.delete(dish)
    await session.flush()
    await _audit(
        session,
        current_user,
        request,
        action="menu.dish_deleted",
        entity_type="menu_dish",
        entity_id=dish.id,
        metadata=metadata,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


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
    planner_categories = await _planner_categories(
        session,
        agency_id=agency_id,
        category_ids=body.category_ids,
    )
    seed = secrets.randbelow(2**63 - 1)
    assignments = _generate_or_422(
        planner_categories,
        trip_days=body.trip_days,
        seed=seed,
    )
    selected_category_ids = [str(category.id) for category in planner_categories]
    plan = MealPlanModel(
        agency_id=agency_id,
        name=body.name,
        trip_days=body.trip_days,
        start_date=body.start_date,
        selected_category_ids=selected_category_ids,
        generation_seed=seed,
        created_by_user_id=current_user.id,
    )
    session.add(plan)
    await session.flush()
    entries = _meal_plan_entries(plan.id, assignments)
    session.add_all(entries)
    await session.flush()
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
    plan = await _get_plan(session, plan_id, agency_id)
    category_ids = body.category_ids
    if category_ids is None and plan.selected_category_ids:
        category_ids = [uuid.UUID(str(category_id)) for category_id in plan.selected_category_ids]

    planner_categories = await _planner_categories(
        session,
        agency_id=agency_id,
        category_ids=category_ids,
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
    plan = await _get_plan(session, plan_id, agency_id, include_entries=True)
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
    plan = await _get_plan(session, plan_id, agency_id, include_entries=True)
    entry = next((item for item in plan.entries if item.id == entry_id), None)
    if entry is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Meal plan entry not found",
        )
    dish, category = await _get_dish(session, body.dish_id, agency_id)
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


@router.get(
    "/plans/{plan_id}/export.xlsx",
    summary="Export a saved meal plan to Excel",
)
async def export_meal_plan(
    plan_id: uuid.UUID,
    current_user: User = Depends(require_role(MENU_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> Response:
    agency_id = _agency_scope(current_user)
    plan = await _get_plan(session, plan_id, agency_id, include_entries=True)
    content = MealPlanExcelExporter().export(
        plan_name=plan.name,
        trip_days=plan.trip_days,
        start_date=plan.start_date,
        selected_category_ids=[
            uuid.UUID(str(category_id)) for category_id in plan.selected_category_ids
        ],
        entries=[
            MealPlanExportEntry(
                day_number=entry.day_number,
                meal_type=entry.meal_type,
                category_id=entry.category_id,
                category_name=entry.category_name,
                dish_name=entry.dish_name,
                notes=entry.notes,
            )
            for entry in plan.entries
        ],
    )
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": (f'attachment; filename="{_excel_filename(plan.name)}"')},
    )


@router.delete(
    "/plans/{plan_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a saved meal plan",
)
async def delete_meal_plan(
    plan_id: uuid.UUID,
    request: Request,
    current_user: User = Depends(require_role(MENU_ROLES)),
    session: AsyncSession = Depends(get_db_session),
    _csrf: None = Depends(require_cookie_csrf),
) -> Response:
    agency_id = _agency_scope(current_user)
    plan = await _get_plan(session, plan_id, agency_id)
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


def _agency_scope(current_user: User) -> uuid.UUID | None:
    if current_user.agency_id is None and current_user.role != UserRole.SUPER_ADMIN:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User is not assigned to an agency",
        )
    return current_user.agency_id


def _category_scope(
    model: type[MenuCategoryModel],
    agency_id: uuid.UUID | None,
):
    if agency_id is None:
        return model.agency_id.is_(None)
    return model.agency_id == agency_id


def _plan_scope(
    model: type[MealPlanModel],
    agency_id: uuid.UUID | None,
):
    if agency_id is None:
        return model.agency_id.is_(None)
    return model.agency_id == agency_id


async def _get_category(
    session: AsyncSession,
    category_id: uuid.UUID,
    agency_id: uuid.UUID | None,
    *,
    include_dishes: bool = False,
) -> MenuCategoryModel:
    statement = select(MenuCategoryModel).where(
        MenuCategoryModel.id == category_id,
        _category_scope(MenuCategoryModel, agency_id),
    )
    if include_dishes:
        statement = statement.options(selectinload(MenuCategoryModel.dishes))
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
) -> tuple[MenuDishModel, MenuCategoryModel]:
    result = await session.execute(
        select(MenuDishModel, MenuCategoryModel)
        .join(MenuCategoryModel, MenuCategoryModel.id == MenuDishModel.category_id)
        .where(
            MenuDishModel.id == dish_id,
            _category_scope(MenuCategoryModel, agency_id),
        )
    )
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
) -> MealPlanModel:
    statement = select(MealPlanModel).where(
        MealPlanModel.id == plan_id,
        _plan_scope(MealPlanModel, agency_id),
    )
    if include_entries:
        statement = statement.options(selectinload(MealPlanModel.entries))
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


async def _planner_categories(
    session: AsyncSession,
    *,
    agency_id: uuid.UUID | None,
    category_ids: list[uuid.UUID] | None,
) -> list[PlannerCategory]:
    if category_ids is not None and not category_ids:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Select at least one category",
        )

    statement = (
        select(MenuCategoryModel)
        .where(_category_scope(MenuCategoryModel, agency_id))
        .options(selectinload(MenuCategoryModel.dishes))
        .order_by(MenuCategoryModel.sort_order, func.lower(MenuCategoryModel.name))
    )
    if category_ids is not None:
        statement = statement.where(MenuCategoryModel.id.in_(category_ids))

    category_result = await session.execute(statement)
    categories = list(category_result.scalars().unique().all())
    if category_ids is not None:
        categories_by_id = {category.id: category for category in categories}
        if set(categories_by_id) != set(category_ids):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="One or more selected categories are unavailable",
            )
        categories = [categories_by_id[category_id] for category_id in category_ids]

    planner_categories: list[PlannerCategory] = []
    for category in categories:
        active_dishes = sorted(
            (dish for dish in category.dishes if dish.is_active),
            key=lambda dish: (
                dish.sort_order,
                dish.name.casefold(),
                str(dish.id),
            ),
        )
        if category_ids is None and not active_dishes:
            continue
        planner_categories.append(
            PlannerCategory(
                id=category.id,
                name=category.name,
                dishes=tuple(
                    PlannerDish(
                        id=dish.id,
                        category_id=category.id,
                        name=dish.name,
                        category_name=category.name,
                        sort_order=dish.sort_order,
                    )
                    for dish in active_dishes
                ),
            )
        )

    if not planner_categories:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Select at least one category with active dishes",
        )
    return planner_categories


def _generate_or_422(
    planner_categories: list[PlannerCategory],
    *,
    trip_days: int,
    seed: int,
) -> list[MealSlotAssignment]:
    try:
        return generate_balanced_meal_assignments(
            planner_categories,
            trip_days=trip_days,
            seed=seed,
        )
    except InsufficientCategoryDishesError as exc:
        shortages = "; ".join(
            (
                f"{shortage.category_name}: add {shortage.missing} "
                f"dish{'es' if shortage.missing != 1 else ''}"
            )
            for shortage in exc.shortages
        )
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                f"Each selected category needs {exc.required_per_category} active "
                f"dishes for a {trip_days}-day lunch and dinner plan. {shortages}."
            ),
        ) from exc


def _meal_plan_entries(
    plan_id: uuid.UUID,
    assignments: list[MealSlotAssignment],
) -> list[MealPlanEntryModel]:
    return [
        MealPlanEntryModel(
            plan_id=plan_id,
            day_number=assignment.day_number,
            meal_type=assignment.meal_type,
            dish_id=assignment.dish.id,
            category_id=assignment.dish.category_id,
            dish_name=assignment.dish.name,
            category_name=assignment.dish.category_name,
        )
        for assignment in assignments
    ]


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


def _normalized_name(value: str) -> str:
    return " ".join(value.strip().split()).casefold()


def _excel_filename(plan_name: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9]+", "-", plan_name).strip("-").lower()
    return f"{(normalized[:80] or 'meal-plan')}.xlsx"


def _utcnow() -> datetime:
    return datetime.now(tz=UTC)


async def _audit(
    session: AsyncSession,
    current_user: User,
    request: Request,
    *,
    action: str,
    entity_type: str,
    entity_id: uuid.UUID,
    metadata: dict[str, object],
) -> None:
    await AuditLogRepository(session).record(
        action=action,
        entity_type=entity_type,
        agency_id=current_user.agency_id,
        user_id=current_user.id,
        actor_email=current_user.email,
        entity_id=str(entity_id),
        ip_address=trusted_client_ip(request),
        metadata=metadata,
    )
