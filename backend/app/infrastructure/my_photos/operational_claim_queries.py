"""Acquire durable operation scope in the same order as cancellation/results."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.my_photos_models import MyPhotoGalleryModel, MyPhotoJobModel


def gallery_allows_operations(gallery: MyPhotoGalleryModel) -> bool:
    return gallery.feature_enabled and gallery.status not in {"failed", "removed"}


async def locked_claim_candidate(
    session: AsyncSession, job_id: uuid.UUID
) -> tuple[MyPhotoJobModel, MyPhotoGalleryModel] | None:
    # Read only immutable scope columns before taking locks. Loading the job
    # first with FOR UPDATE would reverse cancellation's gallery -> job order.
    scope = (
        await session.execute(
            select(
                MyPhotoJobModel.gallery_id, MyPhotoJobModel.agency_id, MyPhotoJobModel.group_id
            ).where(MyPhotoJobModel.id == job_id)
        )
    ).one_or_none()
    if scope is None:
        return None
    gallery = (
        await session.execute(
            select(MyPhotoGalleryModel)
            .where(
                MyPhotoGalleryModel.id == scope.gallery_id,
                MyPhotoGalleryModel.agency_id == scope.agency_id,
                MyPhotoGalleryModel.group_id == scope.group_id,
            )
            .execution_options(populate_existing=True)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if gallery is None:
        return None
    job = (
        await session.execute(
            select(MyPhotoJobModel)
            .where(
                MyPhotoJobModel.id == job_id,
                MyPhotoJobModel.gallery_id == gallery.id,
                MyPhotoJobModel.agency_id == gallery.agency_id,
                MyPhotoJobModel.group_id == gallery.group_id,
            )
            .execution_options(populate_existing=True)
            .with_for_update()
        )
    ).scalar_one_or_none()
    return None if job is None else (job, gallery)
