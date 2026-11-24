"""Revision-fenced category creation, rename and deletion."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.use_cases.menu.create_menu import create_category
from app.domain.entities.entities import User
from app.infrastructure.database.session import get_db_session
from app.presentation.api.v1.schemas.menu_schemas import (
    CreateMenuCategoryRequest,
    MenuCategoryResponse,
    MenuRevisionRequest,
    UpdateMenuCategoryRequest,
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
from .menu_presenters import _category_response
from .menu_queries import _ensure_category_name_available, _get_category

router = APIRouter()


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
    category = await create_category(
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
    category = await _get_category(
        session,
        category_id,
        agency_id,
        include_dishes=True,
        lock=True,
    )
    _require_current_revision(
        actual=category.updated_at,
        expected=body.expected_updated_at,
        resource="menu category",
    )
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
    body: MenuRevisionRequest,
    request: Request,
    current_user: User = Depends(require_role(MENU_ROLES)),
    session: AsyncSession = Depends(get_db_session),
    _csrf: None = Depends(require_cookie_csrf),
) -> Response:
    agency_id = _agency_scope(current_user)
    category = await _get_category(
        session,
        category_id,
        agency_id,
        include_dishes=True,
        lock=True,
    )
    _require_current_revision(
        actual=category.updated_at,
        expected=body.expected_updated_at,
        resource="menu category",
    )
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
