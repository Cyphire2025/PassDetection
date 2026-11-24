"""Bounded aggregate counts for one passenger and published gallery revision."""

from __future__ import annotations

import uuid

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.my_photos.states import MEDIA_DELIVERY_READY_STATES, MEDIA_PREPARING_STATES
from app.infrastructure.database.my_photos_models import (
    MyPhotoGalleryModel,
    MyPhotoMatchModel,
    MyPhotoMediaAssetModel,
    MyPhotoSearchRunModel,
)
from app.presentation.api.v1.schemas.my_photos_schemas import MyPhotosResultsResponse


async def active_result_counts(
    session: AsyncSession,
    *,
    gallery: MyPhotoGalleryModel,
    group_id: uuid.UUID,
    passenger_identity_id: uuid.UUID,
    search: MyPhotoSearchRunModel | None,
) -> MyPhotosResultsResponse:
    """Query one active result snapshot with bounded aggregate SQL."""
    effective_result_revision = (
        await session.execute(
            select(func.max(MyPhotoMatchModel.gallery_revision)).where(
                MyPhotoMatchModel.passenger_identity_id == passenger_identity_id,
                MyPhotoMatchModel.group_id == group_id,
                MyPhotoMatchModel.gallery_revision <= gallery.published_revision,
                MyPhotoMatchModel.active.is_(True),
            )
        )
    ).scalar_one()
    prior_revision = (
        await session.execute(
            select(func.max(MyPhotoSearchRunModel.gallery_revision)).where(
                MyPhotoSearchRunModel.passenger_identity_id == passenger_identity_id,
                MyPhotoSearchRunModel.group_id == group_id,
                MyPhotoSearchRunModel.status == "complete",
                MyPhotoSearchRunModel.gallery_revision < gallery.published_revision,
            )
        )
    ).scalar_one()
    aggregate = (
        await session.execute(
            select(
                func.count(MyPhotoMatchModel.id),
                func.coalesce(
                    func.sum(
                        case(
                            (
                                MyPhotoMediaAssetModel.availability_state.in_(
                                    tuple(MEDIA_DELIVERY_READY_STATES)
                                ),
                                1,
                            ),
                            else_=0,
                        )
                    ),
                    0,
                ),
                func.coalesce(
                    func.sum(
                        case(
                            (
                                MyPhotoMediaAssetModel.availability_state.in_(
                                    tuple(MEDIA_PREPARING_STATES)
                                ),
                                1,
                            ),
                            else_=0,
                        )
                    ),
                    0,
                ),
                func.max(MyPhotoMatchModel.updated_at),
            )
            .select_from(MyPhotoMatchModel)
            .join(
                MyPhotoMediaAssetModel,
                MyPhotoMediaAssetModel.id == MyPhotoMatchModel.media_asset_id,
            )
            .where(
                MyPhotoMatchModel.passenger_identity_id == passenger_identity_id,
                MyPhotoMatchModel.group_id == group_id,
                MyPhotoMatchModel.gallery_revision == effective_result_revision,
                MyPhotoMatchModel.active.is_(True),
                MyPhotoMediaAssetModel.availability_state != "removed",
            )
        )
    ).one()
    new_photo_count = 0
    if prior_revision is not None and effective_result_revision == gallery.published_revision:
        prior_match = MyPhotoMatchModel.__table__.alias("prior_match")
        new_photo_count = int(
            (
                await session.execute(
                    select(func.count(MyPhotoMatchModel.id)).where(
                        MyPhotoMatchModel.passenger_identity_id == passenger_identity_id,
                        MyPhotoMatchModel.group_id == group_id,
                        MyPhotoMatchModel.gallery_revision == gallery.published_revision,
                        MyPhotoMatchModel.active.is_(True),
                        MyPhotoMatchModel.media_asset_id.in_(
                            select(MyPhotoMediaAssetModel.id).where(
                                MyPhotoMediaAssetModel.gallery_id == gallery.id,
                                MyPhotoMediaAssetModel.availability_state != "removed",
                            )
                        ),
                        ~select(prior_match.c.id)
                        .where(
                            prior_match.c.passenger_identity_id == passenger_identity_id,
                            prior_match.c.group_id == group_id,
                            prior_match.c.gallery_revision == prior_revision,
                            prior_match.c.media_asset_id == MyPhotoMatchModel.media_asset_id,
                        )
                        .exists(),
                    )
                )
            ).scalar_one()
        )
    return MyPhotosResultsResponse(
        snapshot_revision=(
            int(effective_result_revision)
            if effective_result_revision is not None
            else int(search.gallery_revision)
            if search is not None
            and search.status == "complete"
            and search.gallery_revision <= gallery.published_revision
            else int(prior_revision or gallery.published_revision)
        ),
        match_count=int(aggregate[0] or 0),
        # First-ever results intentionally show zero "new" photos;
        # later revisions count current assets absent from the latest
        # prior completed gallery search, without loading asset IDs.
        new_photo_count=new_photo_count,
        downloadable_count=int(aggregate[1] or 0),
        preparing_count=int(aggregate[2] or 0),
        last_updated_at=aggregate[3],
    )
