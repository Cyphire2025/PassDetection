"""Flush-only retained itinerary version creation shared with the website.

Caller holds the access/group lock, validates the current access revision,
checks policy, supplies the typed schema and owns audit/commit.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.gc_mobile_models import (
    GCGroupAccessModel,
    GCItineraryDayModel,
    GCItineraryItemModel,
    GCItineraryVersionModel,
)


async def create_itinerary_version(
    session: AsyncSession,
    *,
    access: GCGroupAccessModel,
    group_id: uuid.UUID,
    actor_id: uuid.UUID,
    body: Any,
    checksum: str,
) -> GCItineraryVersionModel:
    max_version = int(
        (
            await session.execute(
                select(func.coalesce(func.max(GCItineraryVersionModel.version), 0)).where(
                    GCItineraryVersionModel.gc_group_access_id == access.id
                )
            )
        ).scalar_one()
    )
    now = datetime.now(tz=UTC)
    itinerary = GCItineraryVersionModel(
        id=uuid.uuid4(),
        agency_id=access.agency_id,
        group_id=group_id,
        gc_group_access_id=access.id,
        version=max_version + 1,
        revision=1,
        status="draft",
        title=body.title,
        content_checksum=checksum,
        created_by_user_id=actor_id,
        created_at=now,
        updated_at=now,
    )
    session.add(itinerary)
    await session.flush()
    for day_index, day in enumerate(body.days):
        day_model = GCItineraryDayModel(
            id=uuid.uuid4(),
            agency_id=access.agency_id,
            group_id=group_id,
            gc_group_access_id=access.id,
            itinerary_version_id=itinerary.id,
            day_number=day.day_number,
            trip_date=day.trip_date,
            title=day.title or f"Day {day.day_number}",
            sort_order=day_index,
            created_at=now,
            updated_at=now,
        )
        session.add(day_model)
        await session.flush()
        for item_index, item in enumerate(day.items):
            session.add(
                GCItineraryItemModel(
                    id=uuid.uuid4(),
                    agency_id=access.agency_id,
                    group_id=group_id,
                    gc_group_access_id=access.id,
                    itinerary_version_id=itinerary.id,
                    itinerary_day_id=day_model.id,
                    item_type="activity",
                    title=item.title,
                    description=item.description,
                    starts_at=item.starts_at,
                    ends_at=item.ends_at,
                    location_name=item.location_name,
                    latitude=item.latitude,
                    longitude=item.longitude,
                    sort_order=item.sort_order if item.sort_order else item_index,
                    public_metadata={},
                    created_at=now,
                    updated_at=now,
                )
            )
    access.revision += 1
    access.updated_by_user_id = actor_id
    access.updated_at = now
    await session.flush()
    return itinerary
