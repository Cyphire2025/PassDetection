"""
Notification Repository
=======================
Stores agency-facing operational notifications.
"""

from __future__ import annotations

import base64
import json
import uuid
from datetime import UTC, datetime

from sqlalchemy import and_, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.exceptions.exceptions import EntityNotFoundError
from app.infrastructure.database.models import NotificationModel
from app.infrastructure.repositories.notification_feed_queries import (
    direct_feed_query,
    direct_predicates,
    direct_unread_count,
)


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
        priority: str = "normal",
        category: str = "general",
        dedupe_key: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> NotificationModel:
        if dedupe_key is not None:
            if user_id is None:
                raise ValueError("deduplicated notifications must target one user")
            existing = await self._session.execute(
                select(NotificationModel).where(
                    NotificationModel.user_id == user_id,
                    NotificationModel.dedupe_key == dedupe_key,
                )
            )
            if model := existing.scalar_one_or_none():
                return model
        model = NotificationModel(
            id=uuid.uuid4(),
            agency_id=agency_id,
            user_id=user_id,
            type=type,
            title=title,
            message=message,
            entity_type=entity_type,
            entity_id=entity_id,
            priority=priority,
            category=category,
            dedupe_key=dedupe_key,
            metadata_json=metadata or {},
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
        stmt = stmt.order_by(NotificationModel.created_at.desc(), NotificationModel.id.desc()).offset(skip).limit(limit)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def list_direct_feed(
        self,
        *,
        user_id: uuid.UUID,
        agency_id: uuid.UUID | None,
        unread_only: bool = False,
        priority: str | None = None,
        cursor: str | None = None,
        limit: int = 30,
    ) -> tuple[list[NotificationModel], int, str | None]:
        """Return a stable, personally targeted feed.

        Agency-wide notification rows are intentionally excluded: their shared
        read bit cannot represent per-user state.
        """

        result = await self._session.execute(direct_feed_query(
            user_id=user_id, agency_id=agency_id, unread_only=unread_only,
            priority=priority, after=_decode_cursor(cursor) if cursor is not None else None, limit=limit))
        rows = list(result.scalars().all())
        has_more = len(rows) > limit
        items = rows[:limit]
        count_result = await self._session.execute(direct_unread_count(user_id, agency_id))
        unread_count = int(count_result.scalar_one())
        next_cursor = (
            _encode_cursor(items[-1].created_at, items[-1].id)
            if has_more and items
            else None
        )
        return items, unread_count, next_cursor

    async def acknowledge_direct_read(
        self, *, notification_id: uuid.UUID, user_id: uuid.UUID, agency_id: uuid.UUID | None,
    ) -> tuple[uuid.UUID, datetime | None, bool]:
        """Monotonic acknowledgement; preserve any existing first-read timestamp.

        Only the personally targeted row is locked. Content and metadata are
        never hydrated; caller owns the transaction and durable receipt.
        """
        row = (await self._session.execute(select(
            NotificationModel.agency_id, NotificationModel.is_read, NotificationModel.read_at,
        ).where(NotificationModel.id == notification_id, *direct_predicates(user_id, agency_id))
            .with_for_update(nowait=True))).one_or_none()
        if row is None:
            raise EntityNotFoundError("Notification", str(notification_id))
        if row.is_read:
            return row.agency_id, row.read_at, False
        read_at = row.read_at or datetime.now(tz=UTC)
        await self._session.execute(update(NotificationModel).where(
            NotificationModel.id == notification_id, *direct_predicates(user_id, agency_id),
            NotificationModel.is_read.is_(False),
        ).values(is_read=True, read_at=read_at).execution_options(synchronize_session=False))
        await self._session.flush()
        return row.agency_id, read_at, True

    async def mark_all_direct_read(
        self,
        *,
        user_id: uuid.UUID,
        agency_id: uuid.UUID | None,
    ) -> int:
        now = datetime.now(tz=UTC)
        predicates = [NotificationModel.user_id == user_id]
        if agency_id is not None:
            predicates.append(NotificationModel.agency_id == agency_id)
        result = await self._session.execute(
            update(NotificationModel)
            .where(
                *predicates,
                NotificationModel.is_read.is_(False),
            )
            .values(is_read=True, read_at=now)
            .execution_options(synchronize_session="fetch")
        )
        await self._session.flush()
        return int(result.rowcount or 0)

    async def mark_read(
        self,
        *,
        notification_id: uuid.UUID,
        agency_id: uuid.UUID | None,
        user_id: uuid.UUID,
    ) -> NotificationModel:
        direct_visibility = NotificationModel.user_id == user_id
        if agency_id is not None:
            direct_visibility = and_(
                direct_visibility,
                NotificationModel.agency_id == agency_id,
            )
            visibility = or_(
                direct_visibility,
                and_(
                    NotificationModel.agency_id == agency_id,
                    NotificationModel.user_id.is_(None),
                ),
            )
        else:
            visibility = direct_visibility
        result = await self._session.execute(
            select(NotificationModel).where(
                NotificationModel.id == notification_id,
                visibility,
            )
        )
        model = result.scalar_one_or_none()
        if not model:
            raise EntityNotFoundError("Notification", str(notification_id))
        model.is_read = True
        model.read_at = datetime.now(tz=UTC)
        await self._session.flush()
        return model


def _encode_cursor(created_at: datetime, notification_id: uuid.UUID) -> str:
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=UTC)
    payload = json.dumps(
        {"created_at": created_at.isoformat(), "id": str(notification_id)},
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def _decode_cursor(value: str) -> tuple[datetime, uuid.UUID]:
    try:
        padding = "=" * (-len(value) % 4)
        payload = json.loads(base64.urlsafe_b64decode(value + padding))
        created_at = datetime.fromisoformat(payload["created_at"])
        notification_id = uuid.UUID(payload["id"])
        if created_at.tzinfo is None:
            raise ValueError
        return created_at, notification_id
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("invalid notification cursor") from exc
