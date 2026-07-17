"""
Notification Repository
=======================
Stores agency-facing operational notifications.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.exceptions.exceptions import EntityNotFoundError
from app.infrastructure.database.models import NotificationModel


class NotificationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        agency_id: uuid.UUID,
        type: str,
        title: str,
        message: str,
        user_id: uuid.UUID | None = None,
        entity_type: str | None = None,
        entity_id: str | None = None,
    ) -> NotificationModel:
        model = NotificationModel(
            id=uuid.uuid4(),
            agency_id=agency_id,
            user_id=user_id,
            type=type,
            title=title,
            message=message,
            entity_type=entity_type,
            entity_id=entity_id,
            is_read=False,
            created_at=datetime.now(tz=UTC),
        )
        self._session.add(model)
        await self._session.flush()
        return model

    async def list_for_user(
        self,
        *,
        agency_id: uuid.UUID,
        user_id: uuid.UUID,
        unread_only: bool = False,
        skip: int = 0,
        limit: int = 50,
    ) -> list[NotificationModel]:
        stmt = select(NotificationModel).where(
            NotificationModel.agency_id == agency_id,
            or_(NotificationModel.user_id == user_id, NotificationModel.user_id.is_(None)),
        )
        if unread_only:
            stmt = stmt.where(NotificationModel.is_read.is_(False))
        stmt = stmt.order_by(NotificationModel.created_at.desc()).offset(skip).limit(limit)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def mark_read(self, *, notification_id: uuid.UUID, agency_id: uuid.UUID, user_id: uuid.UUID) -> NotificationModel:
        result = await self._session.execute(
            select(NotificationModel).where(
                NotificationModel.id == notification_id,
                NotificationModel.agency_id == agency_id,
                or_(NotificationModel.user_id == user_id, NotificationModel.user_id.is_(None)),
            )
        )
        model = result.scalar_one_or_none()
        if not model:
            raise EntityNotFoundError("Notification", str(notification_id))
        model.is_read = True
        model.read_at = datetime.now(tz=UTC)
        await self._session.flush()
        return model
