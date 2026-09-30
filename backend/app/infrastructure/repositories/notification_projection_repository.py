"""Bounded scalar personal notifications, never whole ORM/metadata payloads."""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Text, case, cast, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.models import NotificationModel
from app.infrastructure.repositories.notification_feed_queries import (
    direct_feed_query,
    direct_unread_count,
)

TEXT_LIMITS = {"type": 80, "title": 255, "message": 4096, "entity_type": 80,
               "entity_id": 128, "priority": 16, "category": 40}
METADATA_TEXT_LIMITS = {"provider": 32, "account_email": 320, "group_name": 255}


class NotificationProjectionLimitError(ValueError):
    """Only a static failure is public; no partial page is returned."""


class NotificationProjectionRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def page(
        self, *, user_id: UUID, agency_id: UUID | None, unread_only: bool,
        priority: str | None, after: tuple[datetime, UUID] | None,
        cutoff: datetime, limit: int,
    ) -> tuple[list[dict[str, Any]], int]:
        model = NotificationModel
        columns: list[Any] = [model.id, model.agency_id, model.user_id, model.is_read,
                   model.created_at, model.read_at]
        columns.extend(func.substr(getattr(model, name), 1, bound + 1).label(name)
                       for name, bound in TEXT_LIMITS.items())
        for name, bound in METADATA_TEXT_LIMITS.items():
            value = model.metadata_json[name]
            if self.session.get_bind().dialect.name == "postgresql":
                string_type = func.jsonb_typeof(value) == "string"
            else:
                string_type = func.json_type(model.metadata_json, "$." + name) == "text"
            columns.append(case((string_type, func.substr(cast(value.as_string(), Text), 1, bound + 1)),
                                else_=None).label("metadata_" + name))
        query = direct_feed_query(user_id=user_id, agency_id=agency_id,
            unread_only=unread_only, priority=priority, after=after, cutoff=cutoff, limit=limit)
        rows = [dict(row) for row in (await self.session.execute(query.with_only_columns(*columns))).mappings()]
        for row in rows:
            for name, bound in TEXT_LIMITS.items():
                if row[name] is not None and len(row[name]) > bound:
                    raise NotificationProjectionLimitError("Notification field exceeds projection bound")
            metadata = {}
            for name, bound in METADATA_TEXT_LIMITS.items():
                value = row.pop("metadata_" + name)
                if value is not None:
                    if len(value) > bound:
                        raise NotificationProjectionLimitError("Notification metadata exceeds projection bound")
                    metadata[name] = value
            row["metadata"] = metadata
            row["metadata_projection"] = "provider_account_email_group_name_only"
        unread = int(await self.session.scalar(direct_unread_count(user_id, agency_id)) or 0)
        return rows, unread
