"""Revision-fenced dish creation, editing and deletion."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.use_cases.menu.create_menu import create_dish
from app.domain.entities.entities import User
from app.infrastructure.database.session import get_db_session
from app.presentation.api.v1.schemas.menu_schemas import (
    CreateMenuDishRequest,
    MenuDishResponse,
    MenuDishRevisionRequest,
    UpdateMenuDishRequest,
)
from app.presentation.dependencies.auth import require_role
from app.presentation.dependencies.csrf import require_cookie_csrf

from .menu_common import (
    MENU_ROLES,
    _agency_scope,
    _audit,
    _normalized_name,
    _require_current_revision,
    _utcnow,
)
from .menu_creation_support import menu_creation_support
from .menu_presenters import _dish_response
from .menu_queries import _ensure_dish_name_available, _get_dish

router = APIRouter()


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
    dish, category = await create_dish(
        session,
        support=menu_creation_support(),
        agency_id=agency_id,
        actor_id=current_user.id,
        body=body,
        category_id=category_id,
    )
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
    dish, category = await _get_dish(session, dish_id, agency_id, lock=True)
    _require_current_revision(
        actual=dish.updated_at,
        expected=body.expected_updated_at,
        resource="menu dish",
    )
    _require_current_revision(
        actual=category.updated_at,
        expected=body.expected_category_updated_at,
        resource="menu category",
    )
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
    changed_at = _utcnow()
    dish.updated_at = changed_at
    category.updated_at = changed_at
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
    body: MenuDishRevisionRequest,
    request: Request,
    current_user: User = Depends(require_role(MENU_ROLES)),
    session: AsyncSession = Depends(get_db_session),
    _csrf: None = Depends(require_cookie_csrf),
) -> Response:
    agency_id = _agency_scope(current_user)
    dish, category = await _get_dish(session, dish_id, agency_id, lock=True)
    _require_current_revision(
        actual=dish.updated_at,
        expected=body.expected_updated_at,
        resource="menu dish",
    )
    _require_current_revision(
        actual=category.updated_at,
        expected=body.expected_category_updated_at,
        resource="menu category",
    )
    metadata = {"name": dish.name, "category": category.name}
    await session.delete(dish)
    category.updated_at = _utcnow()
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
