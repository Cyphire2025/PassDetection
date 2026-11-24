"""Revision-bound photo pages and idempotent passenger feedback."""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime

from sqlalchemy import and_, func, or_, select

from app.application.my_photos.cursor import GalleryCursor, GalleryCursorCodec
from app.application.my_photos.errors import (
    MyPhotosConflict,
    MyPhotosInvalidCursor,
)
from app.application.my_photos.states import (
    MatchFilter,
)
from app.application.security.mobile_access_policy import AuthorizedMobileTrip
from app.core.security.mobile_jwt import MobileAccessClaims
from app.domain.exceptions.exceptions import EntityNotFoundError
from app.infrastructure.database.my_photos_models import (
    MyPhotoMatchModel,
    MyPhotoMediaAssetModel,
    MyPhotoSearchRunModel,
)
from app.infrastructure.my_photos.audit import record_my_photos_audit
from app.infrastructure.my_photos.context import MyPhotosContext
from app.infrastructure.my_photos.delivery_service import MyPhotosDeliveryService
from app.infrastructure.my_photos.telemetry import my_photos_metrics
from app.presentation.api.v1.schemas.my_photos_schemas import (
    MyPhotosFeedbackRequest,
    MyPhotosFeedbackResponse,
    MyPhotosPhotoPageResponse,
)


class MyPhotosCatalogService:
    def __init__(self, context: MyPhotosContext, *, delivery: MyPhotosDeliveryService) -> None:
        self._context = context
        self._delivery = delivery
        self._cursor = GalleryCursorCodec(context.settings.app_secret_key)

    async def photo_page(
        self,
        *,
        claims: MobileAccessClaims,
        trip: AuthorizedMobileTrip,
        match_filter: MatchFilter,
        cursor: str | None,
        limit: int,
    ) -> MyPhotosPhotoPageResponse:
        identity = self._context._require_passenger(claims, trip)
        gallery = await self._context._ready_gallery(claims.agency_id, trip.group.id)
        limit = min(limit, self._context.settings.my_photos.maximum_page_size)
        effective_match_revision = (
            await self._context.session.execute(
                select(func.max(MyPhotoMatchModel.gallery_revision)).where(
                    MyPhotoMatchModel.passenger_identity_id == identity.id,
                    MyPhotoMatchModel.group_id == trip.group.id,
                    MyPhotoMatchModel.gallery_revision <= gallery.published_revision,
                    MyPhotoMatchModel.active.is_(True),
                )
            )
        ).scalar_one()
        latest_completed_revision = (
            await self._context.session.execute(
                select(func.max(MyPhotoSearchRunModel.gallery_revision)).where(
                    MyPhotoSearchRunModel.passenger_identity_id == identity.id,
                    MyPhotoSearchRunModel.group_id == trip.group.id,
                    MyPhotoSearchRunModel.gallery_revision <= gallery.published_revision,
                    MyPhotoSearchRunModel.status == "complete",
                )
            )
        ).scalar_one()
        snapshot_revision = (
            gallery.published_revision
            if match_filter == "all"
            else int(latest_completed_revision or gallery.published_revision)
            if effective_match_revision is None
            else int(effective_match_revision)
        )
        try:
            decoded = (
                self._cursor.decode(
                    cursor,
                    passenger_id=identity.id,
                    group_id=trip.group.id,
                    revision=snapshot_revision,
                    match_filter=match_filter,
                )
                if cursor is not None
                else None
            )
        except MyPhotosInvalidCursor as exc:
            my_photos_metrics.pagination_error(
                "stale" if exc.code == "MY_PHOTOS_CURSOR_STALE" else "invalid"
            )
            raise
        query_rows: list[tuple[MyPhotoMatchModel | None, MyPhotoMediaAssetModel]]
        if match_filter == "all":
            if not gallery.all_group_photos_enabled:
                raise MyPhotosConflict(
                    "MY_PHOTOS_ALL_GROUP_DISABLED",
                    "All Group Photos is not enabled for this trip.",
                )
            join_condition = and_(
                MyPhotoMatchModel.media_asset_id == MyPhotoMediaAssetModel.id,
                MyPhotoMatchModel.passenger_identity_id == identity.id,
                MyPhotoMatchModel.gallery_revision == effective_match_revision,
                MyPhotoMatchModel.active.is_(True),
            )
            statement = (
                select(MyPhotoMatchModel, MyPhotoMediaAssetModel)
                .select_from(MyPhotoMediaAssetModel)
                .outerjoin(MyPhotoMatchModel, join_condition)
                .where(
                    MyPhotoMediaAssetModel.gallery_id == gallery.id,
                    MyPhotoMediaAssetModel.agency_id == claims.agency_id,
                    MyPhotoMediaAssetModel.group_id == trip.group.id,
                    MyPhotoMediaAssetModel.published_revision <= gallery.published_revision,
                    MyPhotoMediaAssetModel.processing_state != "removed",
                    MyPhotoMediaAssetModel.availability_state != "removed",
                )
            )
            if decoded is not None:
                statement = statement.where(
                    or_(
                        MyPhotoMediaAssetModel.sort_rank > decoded.sort_rank,
                        and_(
                            MyPhotoMediaAssetModel.sort_rank == decoded.sort_rank,
                            MyPhotoMediaAssetModel.id > decoded.asset_id,
                        ),
                    )
                )
            statement = statement.order_by(
                MyPhotoMediaAssetModel.sort_rank, MyPhotoMediaAssetModel.id
            ).limit(limit + 1)
            query_rows = list((await self._context.session.execute(statement)).tuples().all())
            total_count = int(
                (
                    await self._context.session.execute(
                        select(func.count(MyPhotoMediaAssetModel.id)).where(
                            MyPhotoMediaAssetModel.gallery_id == gallery.id,
                            MyPhotoMediaAssetModel.published_revision <= gallery.published_revision,
                            MyPhotoMediaAssetModel.processing_state != "removed",
                            MyPhotoMediaAssetModel.availability_state != "removed",
                        )
                    )
                ).scalar_one()
            )
        else:
            latest = await self._context._latest_search(identity.id, trip.group.id)
            if effective_match_revision is None and (latest is None or latest.status != "complete"):
                raise MyPhotosConflict(
                    "MY_PHOTOS_SEARCH_INCOMPLETE",
                    "Your photo search is not complete yet.",
                )
            statement = (
                select(MyPhotoMatchModel, MyPhotoMediaAssetModel)
                .join(
                    MyPhotoMediaAssetModel,
                    and_(
                        MyPhotoMediaAssetModel.id == MyPhotoMatchModel.media_asset_id,
                        MyPhotoMediaAssetModel.agency_id == MyPhotoMatchModel.agency_id,
                        MyPhotoMediaAssetModel.group_id == MyPhotoMatchModel.group_id,
                    ),
                )
                .where(
                    MyPhotoMatchModel.passenger_identity_id == identity.id,
                    MyPhotoMatchModel.agency_id == claims.agency_id,
                    MyPhotoMatchModel.group_id == trip.group.id,
                    MyPhotoMatchModel.gallery_revision == effective_match_revision,
                    MyPhotoMatchModel.active.is_(True),
                    MyPhotoMatchModel.display_tier == match_filter,
                    MyPhotoMediaAssetModel.availability_state != "removed",
                )
            )
            if decoded is not None:
                statement = statement.where(
                    or_(
                        MyPhotoMatchModel.sort_rank > decoded.sort_rank,
                        and_(
                            MyPhotoMatchModel.sort_rank == decoded.sort_rank,
                            MyPhotoMatchModel.media_asset_id > decoded.asset_id,
                        ),
                    )
                )
            statement = statement.order_by(
                MyPhotoMatchModel.sort_rank, MyPhotoMatchModel.media_asset_id
            ).limit(limit + 1)
            query_rows = list((await self._context.session.execute(statement)).tuples().all())
            total_count = int(
                (
                    await self._context.session.execute(
                        select(func.count(MyPhotoMatchModel.id)).where(
                            MyPhotoMatchModel.passenger_identity_id == identity.id,
                            MyPhotoMatchModel.group_id == trip.group.id,
                            MyPhotoMatchModel.gallery_revision == effective_match_revision,
                            MyPhotoMatchModel.active.is_(True),
                            MyPhotoMatchModel.display_tier == match_filter,
                            MyPhotoMatchModel.media_asset_id.in_(
                                select(MyPhotoMediaAssetModel.id).where(
                                    MyPhotoMediaAssetModel.gallery_id == gallery.id,
                                    MyPhotoMediaAssetModel.availability_state != "removed",
                                )
                            ),
                        )
                    )
                ).scalar_one()
            )
        has_more = len(query_rows) > limit
        page_rows = query_rows[:limit]
        page_variants = await self._delivery.latest_variants(
            [asset.id for _, asset in page_rows],
            agency_id=claims.agency_id,
            group_id=trip.group.id,
            variant_kinds=("thumbnail", "preview", "optimized"),
        )
        items = [
            self._delivery.photo_response(
                gallery=gallery,
                group_id=trip.group.id,
                account_cache_scope=hashlib.sha256(
                    f"{claims.account_id}|{self._context.settings.app_secret_key}".encode("utf-8")
                ).hexdigest()[:16],
                match=match,
                asset=asset,
                thumbnail_variant=page_variants.get((asset.id, "thumbnail")),
                preview_variant=page_variants.get((asset.id, "preview")),
                optimized_variant=page_variants.get((asset.id, "optimized")),
            )
            for match, asset in page_rows
        ]
        next_cursor = None
        if has_more and page_rows:
            last_match, last_asset = page_rows[-1]
            cursor_sort_rank = (
                last_asset.sort_rank
                if match_filter == "all"
                else last_match.sort_rank
                if last_match is not None
                else last_asset.sort_rank
            )
            next_cursor = self._cursor.encode(
                GalleryCursor(
                    passenger_id=identity.id,
                    group_id=trip.group.id,
                    revision=snapshot_revision,
                    match_filter=match_filter,
                    sort_rank=cursor_sort_rank,
                    asset_id=last_asset.id,
                )
            )
        return MyPhotosPhotoPageResponse(
            snapshot_revision=snapshot_revision,
            filter=match_filter,
            items=items,
            next_cursor=next_cursor,
            page_size=limit,
            total_count=total_count,
        )

    async def record_feedback(
        self,
        *,
        claims: MobileAccessClaims,
        trip: AuthorizedMobileTrip,
        asset_id: uuid.UUID,
        request: MyPhotosFeedbackRequest,
    ) -> MyPhotosFeedbackResponse:
        identity = self._context._require_passenger(claims, trip)
        gallery = await self._context._ready_gallery(claims.agency_id, trip.group.id)
        match = (
            await self._context.session.execute(
                select(MyPhotoMatchModel)
                .where(
                    MyPhotoMatchModel.passenger_identity_id == identity.id,
                    MyPhotoMatchModel.media_asset_id == asset_id,
                    MyPhotoMatchModel.agency_id == claims.agency_id,
                    MyPhotoMatchModel.group_id == trip.group.id,
                    MyPhotoMatchModel.gallery_revision <= gallery.published_revision,
                    MyPhotoMatchModel.active.is_(True),
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if match is None:
            raise EntityNotFoundError("My Photos match", asset_id)
        if match.feedback_idempotency_key == request.idempotency_key:
            if match.feedback != request.feedback:
                raise MyPhotosConflict(
                    "MY_PHOTOS_IDEMPOTENCY_CONFLICT",
                    "This request key was already used for different feedback.",
                )
        else:
            match.feedback = request.feedback
            match.feedback_idempotency_key = request.idempotency_key
            match.updated_at = datetime.now(tz=UTC)
            await self._context.session.flush()
            await record_my_photos_audit(
                self._context.session,
                action="my_photos_match_feedback",
                agency_id=claims.agency_id,
                group_id=trip.group.id,
                outcome=request.feedback,
                gallery_revision=match.gallery_revision,
                configuration_version=match.match_config_version,
            )
        if match.feedback not in {"this_is_me", "not_me"}:
            raise MyPhotosConflict(
                "MY_PHOTOS_FEEDBACK_INVALID",
                "Photo feedback could not be saved. Try again.",
            )
        return MyPhotosFeedbackResponse(
            asset_id=asset_id,
            feedback=match.feedback,
            updated_at=match.updated_at,
        )
