"""Tenant/group-bound GC content version lookups."""

from __future__ import annotations

import uuid

from fastapi import (
    HTTPException,
    status,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.gc_mobile_models import (
    GCAnnouncementModel,
    GCCommonDocumentModel,
    GCGroupAccessModel,
    GCItineraryVersionModel,
)


async def _latest_itinerary(
    session: AsyncSession,
    access: GCGroupAccessModel,
    *,
    prefer_draft: bool,
) -> GCItineraryVersionModel | None:
    statuses = ("draft", "published") if prefer_draft else ("published",)
    for item_status in statuses:
        item = (
            await session.execute(
                select(GCItineraryVersionModel)
                .where(
                    GCItineraryVersionModel.gc_group_access_id == access.id,
                    GCItineraryVersionModel.status == item_status,
                )
                .order_by(GCItineraryVersionModel.version.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if item is not None:
            return item
    return None


async def _get_itinerary(
    session: AsyncSession,
    access: GCGroupAccessModel,
    version_id: uuid.UUID,
    *,
    lock: bool,
) -> GCItineraryVersionModel:
    stmt = select(GCItineraryVersionModel).where(
        GCItineraryVersionModel.id == version_id,
        GCItineraryVersionModel.gc_group_access_id == access.id,
        GCItineraryVersionModel.agency_id == access.agency_id,
        GCItineraryVersionModel.group_id == access.group_id,
    )
    if lock:
        stmt = stmt.with_for_update()
    item = (await session.execute(stmt)).scalar_one_or_none()
    if item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Itinerary version not found"
        )
    return item


async def _get_common_document(
    session: AsyncSession,
    access: GCGroupAccessModel,
    document_id: uuid.UUID,
    *,
    lock: bool,
) -> GCCommonDocumentModel:
    stmt = select(GCCommonDocumentModel).where(
        GCCommonDocumentModel.id == document_id,
        GCCommonDocumentModel.gc_group_access_id == access.id,
        GCCommonDocumentModel.agency_id == access.agency_id,
        GCCommonDocumentModel.group_id == access.group_id,
    )
    if lock:
        stmt = stmt.with_for_update()
    item = (await session.execute(stmt)).scalar_one_or_none()
    if item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Common document not found"
        )
    return item


async def _get_announcement(
    session: AsyncSession,
    access: GCGroupAccessModel,
    announcement_id: uuid.UUID,
    *,
    lock: bool,
) -> GCAnnouncementModel:
    stmt = select(GCAnnouncementModel).where(
        GCAnnouncementModel.id == announcement_id,
        GCAnnouncementModel.gc_group_access_id == access.id,
        GCAnnouncementModel.agency_id == access.agency_id,
        GCAnnouncementModel.group_id == access.group_id,
    )
    if lock:
        stmt = stmt.with_for_update()
    item = (await session.execute(stmt)).scalar_one_or_none()
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Announcement not found")
    return item
