"""Bounded itinerary, common-document and announcement responses."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.gc_mobile_models import (
    GCAnnouncementModel,
    GCCommonDocumentModel,
    GCItineraryDayModel,
    GCItineraryItemModel,
    GCItineraryVersionModel,
)
from app.presentation.api.v1.routes.gc_app_content_scope import (
    _content_status,
    _itinerary_status,
)
from app.presentation.api.v1.schemas.gc_app_schemas import (
    AnnouncementResponse,
    CommonDocumentResponse,
    ItineraryDayInput,
    ItineraryItemInput,
    ItineraryVersionResponse,
)


async def _itinerary_response(
    session: AsyncSession, itinerary: GCItineraryVersionModel
) -> ItineraryVersionResponse:
    days = list(
        (
            await session.execute(
                select(GCItineraryDayModel)
                .where(GCItineraryDayModel.itinerary_version_id == itinerary.id)
                .order_by(GCItineraryDayModel.sort_order.asc())
                .limit(365)
            )
        ).scalars()
    )
    items = list(
        (
            await session.execute(
                select(GCItineraryItemModel)
                .where(GCItineraryItemModel.itinerary_version_id == itinerary.id)
                .order_by(
                    GCItineraryItemModel.itinerary_day_id.asc(),
                    GCItineraryItemModel.sort_order.asc(),
                )
                .limit(1_500)
            )
        ).scalars()
    )
    by_day: dict[uuid.UUID, list[ItineraryItemInput]] = {}
    for item in items:
        by_day.setdefault(item.itinerary_day_id, []).append(
            ItineraryItemInput(
                title=item.title,
                description=item.description,
                starts_at=item.starts_at,
                ends_at=item.ends_at,
                location_name=item.location_name,
                latitude=item.latitude,
                longitude=item.longitude,
                sort_order=item.sort_order,
            )
        )
    return ItineraryVersionResponse(
        id=itinerary.id,
        group_id=itinerary.group_id,
        version=itinerary.version,
        status=_itinerary_status(itinerary.status),
        title=itinerary.title,
        published_at=itinerary.published_at,
        created_at=itinerary.created_at,
        updated_at=itinerary.updated_at,
        days=[
            ItineraryDayInput(
                day_number=day.day_number,
                date=day.trip_date,
                title=day.title,
                items=by_day.get(day.id, []),
            )
            for day in days
        ],
    )


def _common_document_response(item: GCCommonDocumentModel) -> CommonDocumentResponse:
    return CommonDocumentResponse(
        id=item.id,
        group_id=item.group_id,
        category=item.category,
        display_name=item.title,
        original_filename=item.safe_filename,
        content_type=item.media_type,
        size_bytes=item.byte_size,
        checksum_sha256=item.checksum_sha256,
        version=item.version,
        status=_content_status(item.status),
        sort_order=item.sort_order,
        available_from=item.availability_starts_at,
        available_until=item.availability_expires_at,
        published_at=item.published_at,
        updated_at=item.updated_at,
    )


def _announcement_response(item: GCAnnouncementModel) -> AnnouncementResponse:
    return AnnouncementResponse(
        id=item.id,
        group_id=item.group_id,
        title=item.title,
        message=item.body,
        priority="important" if item.priority == "high" else item.priority,
        status=_content_status(item.status),
        version=item.version,
        available_from=item.availability_starts_at,
        available_until=item.availability_expires_at,
        published_at=item.published_at,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )
