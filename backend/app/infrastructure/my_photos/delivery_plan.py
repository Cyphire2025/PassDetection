"""Private photo plan operations."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import and_, case, func, or_, select

from app.application.my_photos.states import (
    MEDIA_DELIVERY_READY_STATES,
    MEDIA_PREPARING_STATES,
)
from app.application.security.mobile_access_policy import AuthorizedMobileTrip
from app.core.security.mobile_jwt import MobileAccessClaims
from app.infrastructure.database.my_photos_models import (
    MyPhotoAssetVariantModel,
    MyPhotoMatchModel,
    MyPhotoMediaAssetModel,
)
from app.infrastructure.my_photos.delivery_context import (
    MyPhotosDeliveryContext,
)
from app.infrastructure.my_photos.delivery_policy import (
    _SUPPORTED_DELIVERY_MIME,
)
from app.presentation.api.v1.schemas.my_photos_schemas import (
    MyPhotosDownloadEstimateQualityResponse,
    MyPhotosDownloadPlanResponse,
)


class MyPhotosDownloadPlan:
    def __init__(self, context: MyPhotosDeliveryContext) -> None:
        self._context = context

    async def download_plan(
        self,
        *,
        claims: MobileAccessClaims,
        trip: AuthorizedMobileTrip,
    ) -> MyPhotosDownloadPlanResponse:
        """Return one exact aggregate preflight without enumerating matched assets."""

        identity = self._context.require_passenger(claims, trip)
        gallery = await self._context.ready_gallery(claims.agency_id, trip.group.id)
        effective_revision = (
            await self._context.session.execute(
                select(func.max(MyPhotoMatchModel.gallery_revision)).where(
                    MyPhotoMatchModel.passenger_identity_id == identity.id,
                    MyPhotoMatchModel.group_id == trip.group.id,
                    MyPhotoMatchModel.gallery_revision <= gallery.published_revision,
                    MyPhotoMatchModel.active.is_(True),
                )
            )
        ).scalar_one()
        latest_optimized = (
            select(
                MyPhotoAssetVariantModel.media_asset_id.label("asset_id"),
                func.max(MyPhotoAssetVariantModel.delivery_version).label("delivery_version"),
            )
            .where(
                MyPhotoAssetVariantModel.agency_id == claims.agency_id,
                MyPhotoAssetVariantModel.group_id == trip.group.id,
                MyPhotoAssetVariantModel.variant_kind == "optimized",
                MyPhotoAssetVariantModel.availability_state.notin_(("failed", "removed")),
            )
            .group_by(MyPhotoAssetVariantModel.media_asset_id)
            .subquery()
        )
        now = datetime.now(tz=UTC)
        supported_original = and_(
            MyPhotoMediaAssetModel.availability_state.notin_(("failed", "removed")),
            MyPhotoMediaAssetModel.processing_state != "removed",
            MyPhotoMediaAssetModel.mime_type.in_(tuple(_SUPPORTED_DELIVERY_MIME)),
            or_(
                MyPhotoMediaAssetModel.archive_reference.is_not(None),
                MyPhotoMediaAssetModel.storage_reference.is_not(None),
            ),
        )
        usable_optimized = and_(
            MyPhotoAssetVariantModel.id.is_not(None),
            MyPhotoAssetVariantModel.storage_reference.is_not(None),
            MyPhotoAssetVariantModel.mime_type.in_(tuple(_SUPPORTED_DELIVERY_MIME)),
            MyPhotoAssetVariantModel.availability_state.in_(tuple(MEDIA_DELIVERY_READY_STATES)),
            MyPhotoAssetVariantModel.byte_size <= MyPhotoMediaAssetModel.byte_size,
            or_(
                MyPhotoAssetVariantModel.expires_at.is_(None),
                MyPhotoAssetVariantModel.expires_at > now,
            ),
        )
        aggregate = (
            await self._context.session.execute(
                select(
                    func.count(MyPhotoMatchModel.id),
                    func.coalesce(
                        func.sum(
                            case(
                                (supported_original, MyPhotoMediaAssetModel.byte_size),
                                else_=0,
                            )
                        ),
                        0,
                    ),
                    func.coalesce(
                        func.max(
                            case(
                                (supported_original, MyPhotoMediaAssetModel.byte_size),
                                else_=0,
                            )
                        ),
                        0,
                    ),
                    func.count(
                        case(
                            (
                                and_(supported_original, usable_optimized),
                                MyPhotoAssetVariantModel.id,
                            ),
                            else_=None,
                        )
                    ),
                    func.coalesce(
                        func.sum(
                            case(
                                (
                                    and_(supported_original, usable_optimized),
                                    MyPhotoAssetVariantModel.byte_size,
                                ),
                                else_=0,
                            )
                        ),
                        0,
                    ),
                    func.coalesce(
                        func.max(
                            case(
                                (
                                    and_(supported_original, usable_optimized),
                                    MyPhotoAssetVariantModel.byte_size,
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
                                    and_(
                                        supported_original,
                                        MyPhotoMediaAssetModel.availability_state.in_(
                                            tuple(MEDIA_DELIVERY_READY_STATES)
                                        ),
                                    ),
                                    1,
                                ),
                                else_=0,
                            )
                        ),
                        0,
                    ),
                    func.coalesce(
                        func.sum(case((supported_original, 1), else_=0)),
                        0,
                    ),
                    func.coalesce(
                        func.sum(
                            case(
                                (
                                    and_(
                                        supported_original,
                                        MyPhotoMediaAssetModel.availability_state.in_(
                                            tuple(MEDIA_PREPARING_STATES)
                                        ),
                                    ),
                                    1,
                                ),
                                else_=0,
                            )
                        ),
                        0,
                    ),
                )
                .select_from(MyPhotoMatchModel)
                .join(
                    MyPhotoMediaAssetModel,
                    and_(
                        MyPhotoMediaAssetModel.id == MyPhotoMatchModel.media_asset_id,
                        MyPhotoMediaAssetModel.agency_id == MyPhotoMatchModel.agency_id,
                        MyPhotoMediaAssetModel.group_id == MyPhotoMatchModel.group_id,
                    ),
                )
                .outerjoin(
                    latest_optimized,
                    latest_optimized.c.asset_id == MyPhotoMediaAssetModel.id,
                )
                .outerjoin(
                    MyPhotoAssetVariantModel,
                    and_(
                        MyPhotoAssetVariantModel.media_asset_id == latest_optimized.c.asset_id,
                        MyPhotoAssetVariantModel.delivery_version
                        == latest_optimized.c.delivery_version,
                        MyPhotoAssetVariantModel.variant_kind == "optimized",
                    ),
                )
                .where(
                    MyPhotoMatchModel.passenger_identity_id == identity.id,
                    MyPhotoMatchModel.agency_id == claims.agency_id,
                    MyPhotoMatchModel.group_id == trip.group.id,
                    MyPhotoMatchModel.gallery_revision == effective_revision,
                    MyPhotoMatchModel.active.is_(True),
                )
            )
        ).one()
        matched_count = int(aggregate[0] or 0)
        prepared_optimized_count = int(aggregate[3] or 0)
        ready_original_count = int(aggregate[6] or 0)
        original_count = int(aggregate[7] or 0)
        supported_optimized_count = prepared_optimized_count
        return MyPhotosDownloadPlanResponse(
            snapshot_revision=(
                int(effective_revision)
                if effective_revision is not None
                else gallery.published_revision
            ),
            matched_item_count=matched_count,
            downloadable_item_count=ready_original_count,
            preparing_item_count=int(aggregate[8] or 0),
            qualities=[
                MyPhotosDownloadEstimateQualityResponse(
                    quality="original",
                    supported_item_count=original_count,
                    exact_byte_total=int(aggregate[1] or 0),
                    maximum_item_bytes=int(aggregate[2] or 0),
                    estimate_complete=original_count == matched_count,
                ),
                MyPhotosDownloadEstimateQualityResponse(
                    quality="optimized",
                    supported_item_count=supported_optimized_count,
                    exact_byte_total=int(aggregate[4] or 0),
                    maximum_item_bytes=int(aggregate[5] or 0),
                    estimate_complete=supported_optimized_count == matched_count,
                ),
            ],
        )
