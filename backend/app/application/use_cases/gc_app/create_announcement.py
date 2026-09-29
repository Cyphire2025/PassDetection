"""Flush-only announcement version insertion; caller owns policy/audit/publication."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.gc_mobile_models import GCAnnouncementModel, GCGroupAccessModel


@dataclass(frozen=True, slots=True)
class AnnouncementContent:
    title: str
    message: str
    priority: Literal["normal", "important", "emergency"]
    available_from: datetime | None
    available_until: datetime | None


async def create_announcement_version(
    session: AsyncSession,
    *,
    access: GCGroupAccessModel,
    actor_id: uuid.UUID,
    content: AnnouncementContent,
    logical_id: uuid.UUID,
    version: int,
) -> GCAnnouncementModel:
    """Append only; never retire, delete or mutate a previous announcement version."""
    now = datetime.now(UTC)
    announcement = GCAnnouncementModel(
        id=uuid.uuid4(),
        agency_id=access.agency_id,
        group_id=access.group_id,
        gc_group_access_id=access.id,
        logical_announcement_id=logical_id,
        version=version,
        category="emergency" if content.priority == "emergency" else "general",
        priority="high" if content.priority == "important" else content.priority,
        title=content.title,
        body=content.message,
        status="draft",
        passenger_visible=False,
        client_manager_visible=False,
        coordinator_visible=False,
        offline_available=True,
        availability_starts_at=content.available_from,
        availability_expires_at=content.available_until,
        created_by_user_id=actor_id,
        created_at=now,
        updated_at=now,
    )
    session.add(announcement)
    access.revision += 1
    access.updated_by_user_id, access.updated_at = actor_id, now
    await session.flush()
    return announcement
