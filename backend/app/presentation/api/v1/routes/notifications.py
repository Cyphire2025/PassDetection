"""
Notification Routes
===================
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.entities import User, UserRole
from app.domain.exceptions.exceptions import EntityNotFoundError
from app.infrastructure.database.session import get_db_session
from app.infrastructure.repositories.notification_repository import NotificationRepository
from app.presentation.api.v1.schemas.operations_schemas import (
    NotificationFeedResponse,
    NotificationReadAllResponse,
    NotificationResponse,
)
from app.presentation.dependencies.auth import get_current_active_user
from app.presentation.dependencies.csrf import require_cookie_csrf

router = APIRouter()


def _direct_notification_agency(user: User) -> uuid.UUID | None:
    if user.role == UserRole.SUPER_ADMIN:
        return None
    return user.agency_id


def _to_response(notification) -> NotificationResponse:  # type: ignore[no-untyped-def]
    return NotificationResponse(
        id=notification.id,
        agency_id=notification.agency_id,
        user_id=notification.user_id,
        type=notification.type,
        title=notification.title,
        message=notification.message,
        entity_type=notification.entity_type,
        entity_id=notification.entity_id,
        priority=notification.priority,
        category=notification.category,
        metadata=notification.metadata_json or {},
        is_read=notification.is_read,
        created_at=notification.created_at,
        read_at=notification.read_at,
    )


@router.get(
    "",
    response_model=list[NotificationResponse],
    status_code=status.HTTP_200_OK,
    summary="List notifications for the current user",
)
async def list_notifications(
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
    unread_only: bool = False,
    skip: int = 0,
    limit: int = 50,
) -> list[NotificationResponse]:
    if not current_user.agency_id:
        return []
    notifications = await NotificationRepository(session).list_for_user(
        agency_id=current_user.agency_id,
        user_id=current_user.id,
        unread_only=unread_only,
        skip=skip,
        limit=limit,
    )
    return [_to_response(item) for item in notifications]


@router.get(
    "/feed",
    response_model=NotificationFeedResponse,
    status_code=status.HTTP_200_OK,
    summary="List personally targeted live notifications",
)
async def notification_feed(
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
    unread_only: bool = False,
    priority: str | None = Query(default=None, pattern="^(urgent|high|normal|low)$"),
    cursor: str | None = Query(default=None, max_length=1000),
    limit: int = Query(default=30, ge=1, le=100),
) -> NotificationFeedResponse:
    direct_agency_id = _direct_notification_agency(current_user)
    if current_user.role != UserRole.SUPER_ADMIN and direct_agency_id is None:
        return NotificationFeedResponse(
            items=[],
            unread_count=0,
            next_cursor=None,
        )
    try:
        items, unread_count, next_cursor = await NotificationRepository(
            session
        ).list_direct_feed(
            user_id=current_user.id,
            agency_id=direct_agency_id,
            unread_only=unread_only,
            priority=priority,
            cursor=cursor,
            limit=limit,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    return NotificationFeedResponse(
        items=[_to_response(item) for item in items],
        unread_count=unread_count,
        next_cursor=next_cursor,
    )


@router.post(
    "/{notification_id}/read",
    response_model=NotificationResponse,
    status_code=status.HTTP_200_OK,
    summary="Mark a notification as read",
    dependencies=[Depends(require_cookie_csrf)],
)
async def mark_notification_read(
    notification_id: uuid.UUID,
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> NotificationResponse:
    direct_agency_id = _direct_notification_agency(current_user)
    if current_user.role != UserRole.SUPER_ADMIN and direct_agency_id is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Notification was not found.",
        )
    try:
        notification = await NotificationRepository(session).mark_read(
            notification_id=notification_id,
            agency_id=direct_agency_id,
            user_id=current_user.id,
        )
        return _to_response(notification)
    except EntityNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=exc.message)


@router.post(
    "/read-all",
    response_model=NotificationReadAllResponse,
    status_code=status.HTTP_200_OK,
    summary="Mark all personally targeted notifications as read",
    dependencies=[Depends(require_cookie_csrf)],
)
async def mark_all_notifications_read(
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> NotificationReadAllResponse:
    direct_agency_id = _direct_notification_agency(current_user)
    if current_user.role != UserRole.SUPER_ADMIN and direct_agency_id is None:
        return NotificationReadAllResponse(marked_read=0)
    marked_read = await NotificationRepository(session).mark_all_direct_read(
        user_id=current_user.id,
        agency_id=direct_agency_id,
    )
    await session.commit()
    return NotificationReadAllResponse(marked_read=marked_read)
