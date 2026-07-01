"""
Notification Routes
===================
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.entities import User
from app.domain.exceptions.exceptions import EntityNotFoundError
from app.infrastructure.database.session import get_db_session
from app.infrastructure.repositories.notification_repository import NotificationRepository
from app.presentation.api.v1.schemas.operations_schemas import NotificationResponse
from app.presentation.dependencies.auth import get_current_active_user

router = APIRouter()


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


@router.post(
    "/{notification_id}/read",
    response_model=NotificationResponse,
    status_code=status.HTTP_200_OK,
    summary="Mark a notification as read",
)
async def mark_notification_read(
    notification_id: uuid.UUID,
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> NotificationResponse:
    if not current_user.agency_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
    try:
        notification = await NotificationRepository(session).mark_read(
            notification_id=notification_id,
            agency_id=current_user.agency_id,
            user_id=current_user.id,
        )
        return _to_response(notification)
    except EntityNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=exc.message)
