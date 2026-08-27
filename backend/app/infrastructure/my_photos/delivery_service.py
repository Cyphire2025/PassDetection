"""Private My Photos media projection, preparation, and delivery service.

The passenger/trip authorization callbacks are supplied by the application
facade so this service cannot create a parallel authorization policy.
"""

from __future__ import annotations

import asyncio
import hashlib
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Literal, cast

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.my_photos.errors import MyPhotosConflict, MyPhotosUnavailable
from app.application.my_photos.providers import (
    DeliveryAuthorization,
    DeliveryRequest,
    DeliveryResolution,
    DeliveryResolutionRequest,
    MediaDeliveryProvider,
)
from app.application.my_photos.states import (
    MEDIA_DELIVERY_READY_STATES,
    MEDIA_PREPARING_STATES,
    MEDIA_REHYDRATABLE_STATES,
    MediaAvailability,
)
from app.application.security.mobile_access_policy import AuthorizedMobileTrip
from app.core.config.settings import Settings
from app.core.security.mobile_jwt import MobileAccessClaims
from app.domain.exceptions.exceptions import EntityNotFoundError
from app.infrastructure.database.gc_mobile_models import MobilePassengerIdentityModel
from app.infrastructure.database.my_photos_models import (
    MyPhotoAssetVariantModel,
    MyPhotoDeliveryAuthorizationModel,
    MyPhotoGalleryModel,
    MyPhotoJobModel,
    MyPhotoMatchModel,
    MyPhotoMediaAssetModel,
)
from app.infrastructure.my_photos.audit import record_my_photos_audit
from app.infrastructure.my_photos.providers import MyPhotosProviderBundle
from app.infrastructure.my_photos.synthetic_media import synthetic_png
from app.infrastructure.my_photos.telemetry import my_photos_metrics
from app.presentation.api.v1.schemas.my_photos_schemas import (
    MyPhotosDownloadAuthorizationItemResponse,
    MyPhotosDownloadAuthorizationRequest,
    MyPhotosDownloadAuthorizationResponse,
    MyPhotosDownloadEstimateQualityResponse,
    MyPhotosDownloadPlanResponse,
    MyPhotosMediaDescriptor,
    MyPhotosPhotoResponse,
    MyPhotosPrepareRequest,
    MyPhotosPrepareResponse,
)

PassengerResolver = Callable[
    [MobileAccessClaims, AuthorizedMobileTrip], MobilePassengerIdentityModel
]
GalleryResolver = Callable[[uuid.UUID, uuid.UUID], Awaitable[MyPhotoGalleryModel]]
PassengerLocker = Callable[[uuid.UUID, uuid.UUID, uuid.UUID], Awaitable[None]]

_SUPPORTED_DELIVERY_MIME = frozenset({"image/jpeg", "image/png", "image/webp"})


class MyPhotosDeliveryService:
    """Bounded media metadata and short-lived delivery authorization operations."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        settings: Settings,
        providers: MyPhotosProviderBundle,
        require_passenger: PassengerResolver,
        ready_gallery: GalleryResolver,
        lock_passenger_identity: PassengerLocker,
    ) -> None:
        self._session = session
        self._settings = settings
        self._providers = providers
        self._require_passenger = require_passenger
        self._ready_gallery = ready_gallery
        self._lock_passenger_identity = lock_passenger_identity

    async def prepare_media(
        self,
        *,
        claims: MobileAccessClaims,
        trip: AuthorizedMobileTrip,
        asset_id: uuid.UUID,
        request: MyPhotosPrepareRequest,
    ) -> MyPhotosPrepareResponse:
        identity = self._require_passenger(claims, trip)
        gallery = await self._ready_gallery(claims.agency_id, trip.group.id)
        asset = (await self._authorized_assets(identity.id, gallery, [asset_id])).get(asset_id)
        if asset is None:
            raise EntityNotFoundError("My Photos asset", asset_id)
        request_fingerprint = hashlib.sha256(
            f"{asset.id}:{request.quality}".encode("ascii")
        ).hexdigest()
        existing = (
            await self._session.execute(
                select(MyPhotoJobModel).where(
                    MyPhotoJobModel.gallery_id == gallery.id,
                    MyPhotoJobModel.job_type == "prepare_media",
                    MyPhotoJobModel.idempotency_key == request.idempotency_key,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            if (
                existing.media_asset_id != asset.id
                or existing.request_fingerprint != request_fingerprint
            ):
                raise MyPhotosConflict(
                    "MY_PHOTOS_IDEMPOTENCY_CONFLICT",
                    "This request key was already used for a different photo.",
                )
            return MyPhotosPrepareResponse(
                asset_id=asset.id,
                state=(
                    "delivery_available"
                    if asset.availability_state in MEDIA_DELIVERY_READY_STATES
                    else "preparing_delivery"
                ),
                preparation_id=(
                    None if asset.availability_state in MEDIA_DELIVERY_READY_STATES else existing.id
                ),
                retry_after_seconds=(
                    None if asset.availability_state in MEDIA_DELIVERY_READY_STATES else 60
                ),
            )
        if asset.availability_state in MEDIA_DELIVERY_READY_STATES:
            return MyPhotosPrepareResponse(
                asset_id=asset.id,
                state="delivery_available",
                preparation_id=None,
                retry_after_seconds=None,
            )
        if (
            asset.availability_state not in MEDIA_REHYDRATABLE_STATES
            or asset.archive_reference is None
        ):
            raise MyPhotosConflict(
                "MY_PHOTOS_MEDIA_PROCESSING",
                "This photo is not ready for delivery yet.",
            )
        job = MyPhotoJobModel(
            gallery_id=gallery.id,
            media_asset_id=asset.id,
            agency_id=gallery.agency_id,
            group_id=gallery.group_id,
            job_type="prepare_media",
            status="queued",
            idempotency_key=request.idempotency_key,
            request_fingerprint=request_fingerprint,
            checkpoint_cursor=request.quality,
            max_attempts=self._settings.my_photos.job_max_attempts,
            total_count=1,
            correlation_id=uuid.uuid4().hex,
        )
        self._session.add(job)
        asset.availability_state = "rehydration_requested"
        my_photos_metrics.rehydration_requested()
        await self._session.flush()
        await record_my_photos_audit(
            self._session,
            action="my_photos_rehydration_requested",
            agency_id=claims.agency_id,
            group_id=trip.group.id,
            outcome=request.quality,
            gallery_revision=gallery.published_revision,
        )
        return MyPhotosPrepareResponse(
            asset_id=asset.id,
            state="rehydration_requested",
            preparation_id=job.id,
            retry_after_seconds=60,
        )

    async def authorize_downloads(
        self,
        *,
        claims: MobileAccessClaims,
        trip: AuthorizedMobileTrip,
        request: MyPhotosDownloadAuthorizationRequest,
    ) -> MyPhotosDownloadAuthorizationResponse:
        identity = self._require_passenger(claims, trip)
        gallery = await self._ready_gallery(claims.agency_id, trip.group.id)
        await self._lock_passenger_identity(identity.id, claims.agency_id, trip.group.id)
        if len(request.items) > self._settings.my_photos.maximum_delivery_batch:
            raise MyPhotosConflict(
                "MY_PHOTOS_DOWNLOAD_BATCH_TOO_LARGE", "Too many photos were requested at once."
            )
        asset_ids = [item.asset_id for item in request.items]
        assets = await self._authorized_assets(identity.id, gallery, asset_ids)
        if set(assets) != set(asset_ids):
            raise EntityNotFoundError("My Photos asset", "unavailable")
        optimized_variants = await self.latest_optimized_variants(
            [item.asset_id for item in request.items if item.quality == "optimized"],
            agency_id=claims.agency_id,
            group_id=trip.group.id,
        )
        if any(
            item.quality == "optimized"
            and not _optimized_variant_is_downloadable(
                optimized_variants.get(item.asset_id),
                assets[item.asset_id],
            )
            for item in request.items
        ):
            raise MyPhotosConflict(
                "MY_PHOTOS_QUALITY_UNAVAILABLE",
                "Optimized quality is not available for one or more selected photos.",
            )
        content_versions: dict[tuple[uuid.UUID, str], int] = {
            (item.asset_id, item.quality): _content_version(
                quality=item.quality,
                optimized_variant=optimized_variants.get(item.asset_id),
            )
            for item in request.items
        }
        fingerprint = _delivery_request_fingerprint(request, content_versions)
        existing_rows = list(
            (
                await self._session.execute(
                    select(MyPhotoDeliveryAuthorizationModel)
                    .where(
                        MyPhotoDeliveryAuthorizationModel.passenger_identity_id == identity.id,
                        MyPhotoDeliveryAuthorizationModel.group_id == trip.group.id,
                        MyPhotoDeliveryAuthorizationModel.idempotency_key
                        == request.idempotency_key,
                    )
                    .with_for_update()
                )
            ).scalars()
        )
        if existing_rows and any(row.request_fingerprint != fingerprint for row in existing_rows):
            raise MyPhotosConflict(
                "MY_PHOTOS_IDEMPOTENCY_CONFLICT",
                "This request key was already used for a different download selection.",
            )
        existing_by_item = {(row.media_asset_id, row.quality): row for row in existing_rows}
        now = datetime.now(tz=UTC)
        pending_calls: list[tuple[uuid.UUID, str, DeliveryRequest]] = []
        for item in request.items:
            asset = assets[item.asset_id]
            optimized_variant = optimized_variants.get(item.asset_id)
            source_availability = (
                optimized_variant.availability_state
                if item.quality == "optimized" and optimized_variant is not None
                else asset.availability_state
            )
            source_size = (
                optimized_variant.byte_size
                if item.quality == "optimized" and optimized_variant is not None
                else asset.byte_size
            )
            source_checksum = (
                optimized_variant.checksum_sha256
                if item.quality == "optimized" and optimized_variant is not None
                else asset.checksum_sha256
            )
            source_content_type = (
                optimized_variant.mime_type
                if item.quality == "optimized" and optimized_variant is not None
                else asset.mime_type
            )
            source_reference = (
                optimized_variant.storage_reference
                if item.quality == "optimized" and optimized_variant is not None
                else asset.storage_reference
            )
            if source_content_type not in _SUPPORTED_DELIVERY_MIME:
                raise MyPhotosConflict(
                    "MY_PHOTOS_QUALITY_UNAVAILABLE",
                    "A supported normalized photo quality is not available.",
                )
            if source_availability in MEDIA_DELIVERY_READY_STATES and source_reference is None:
                raise MyPhotosConflict(
                    "MY_PHOTOS_MEDIA_UNAVAILABLE",
                    "This photo is not ready for delivery yet.",
                )
            authorization = existing_by_item.get((item.asset_id, item.quality))
            if authorization is None:
                authorization = MyPhotoDeliveryAuthorizationModel(
                    id=uuid.uuid4(),
                    passenger_identity_id=identity.id,
                    passenger_submission_id=identity.passenger_submission_id,
                    gc_group_access_id=trip.access.id,
                    media_asset_id=asset.id,
                    agency_id=claims.agency_id,
                    group_id=trip.group.id,
                    quality=item.quality,
                    status="authorizing",
                    idempotency_key=request.idempotency_key,
                    request_fingerprint=fingerprint,
                    delivery_version=content_versions[(item.asset_id, item.quality)],
                )
                self._session.add(authorization)
                existing_by_item[(item.asset_id, item.quality)] = authorization
            elif (
                authorization.status == "available"
                and authorization.expires_at is not None
                and _as_utc(authorization.expires_at) > now
            ):
                continue
            elif (
                authorization.status == "authorizing"
                and authorization.claim_expires_at is not None
                and _as_utc(authorization.claim_expires_at) > now
            ):
                continue
            claim_token = uuid.uuid4().hex
            authorization.status = "authorizing"
            authorization.claim_token = claim_token
            authorization.claim_expires_at = now + timedelta(
                seconds=self._settings.my_photos.delivery_claim_seconds
            )
            self._clear_delivery_metadata(authorization)
            if source_availability not in MEDIA_DELIVERY_READY_STATES:
                authorization.status = (
                    "preparing" if source_availability in MEDIA_PREPARING_STATES else "failed"
                )
                authorization.claim_token = None
                authorization.claim_expires_at = None
                authorization.stable_error_code = (
                    None if source_availability in MEDIA_PREPARING_STATES else "MEDIA_UNAVAILABLE"
                )
                continue
            pending_calls.append(
                (
                    authorization.id,
                    claim_token,
                    DeliveryRequest(
                        tenant_scope=str(claims.agency_id),
                        group_scope=str(trip.group.id),
                        passenger_scope=str(identity.id),
                        authorization_identity=(
                            _authorization_identity(
                                authorization.id, authorization.delivery_version
                            )
                        ),
                        asset_identity=asset.immutable_asset_key,
                        media_reference=cast(str, source_reference),
                        quality=item.quality,
                        availability_state=cast("MediaAvailability", source_availability),
                        expected_size_bytes=source_size,
                        checksum_sha256=source_checksum,
                        content_type=cast(
                            "Literal['image/jpeg', 'image/png', 'image/webp']",
                            "image/png"
                            if self._providers.provider_name == "development"
                            else source_content_type,
                        ),
                    ),
                )
            )
        await self._session.flush()

        provider_results: list[tuple[uuid.UUID, str, DeliveryAuthorization | None, str | None]] = []
        if pending_calls:
            # Persist the claims and release the passenger/authorization locks
            # before bounded provider I/O. No URL or credential is stored here.
            await self._session.commit()
            provider_results = list(
                await _authorize_provider_batch(
                    provider=self._providers.media,
                    pending_calls=tuple(pending_calls),
                    maximum_ttl_seconds=(
                        self._settings.my_photos.delivery_authorization_ttl_seconds
                    ),
                    timeout_seconds=self._settings.my_photos.media_provider_timeout_seconds,
                    concurrency=self._settings.my_photos.delivery_authorization_concurrency,
                    maximum_batch_size=self._settings.my_photos.maximum_delivery_batch,
                )
            )
            await self._finalize_delivery_claims(provider_results)

        refreshed_rows = list(
            (
                await self._session.execute(
                    select(MyPhotoDeliveryAuthorizationModel).where(
                        MyPhotoDeliveryAuthorizationModel.passenger_identity_id == identity.id,
                        MyPhotoDeliveryAuthorizationModel.group_id == trip.group.id,
                        MyPhotoDeliveryAuthorizationModel.idempotency_key
                        == request.idempotency_key,
                    )
                )
            ).scalars()
        )
        refreshed_by_item = {(row.media_asset_id, row.quality): row for row in refreshed_rows}
        if pending_calls:
            await record_my_photos_audit(
                self._session,
                action="my_photos_download_authorized",
                agency_id=claims.agency_id,
                group_id=trip.group.id,
                outcome=(
                    "issued"
                    if any(row.status == "available" for row in refreshed_rows)
                    else "pending"
                ),
                gallery_revision=gallery.published_revision,
            )
        return MyPhotosDownloadAuthorizationResponse(
            authorizations=[
                self._delivery_response_item(
                    group_id=trip.group.id,
                    authorization=refreshed_by_item[(item.asset_id, item.quality)],
                    transport=refreshed_by_item[(item.asset_id, item.quality)].transport,
                    retry_after_seconds=(
                        self._settings.my_photos.provider_retry_after_seconds
                        if refreshed_by_item[(item.asset_id, item.quality)].status
                        in {"authorizing", "preparing", "failed"}
                        else None
                    ),
                )
                for item in request.items
            ]
        )

    async def download_plan(
        self,
        *,
        claims: MobileAccessClaims,
        trip: AuthorizedMobileTrip,
    ) -> MyPhotosDownloadPlanResponse:
        """Return one exact aggregate preflight without enumerating matched assets."""

        identity = self._require_passenger(claims, trip)
        gallery = await self._ready_gallery(claims.agency_id, trip.group.id)
        effective_revision = (
            await self._session.execute(
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
            await self._session.execute(
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

    async def development_download_content(
        self,
        *,
        claims: MobileAccessClaims,
        trip: AuthorizedMobileTrip,
        authorization_id: uuid.UUID,
    ) -> tuple[bytes, str, str]:
        identity = self._require_passenger(claims, trip)
        if (
            self._settings.app_env != "development"
            or self._providers.provider_name != "development"
        ):
            raise EntityNotFoundError("Photo delivery", authorization_id)
        await self._ready_gallery(claims.agency_id, trip.group.id)
        row = (
            await self._session.execute(
                select(MyPhotoDeliveryAuthorizationModel, MyPhotoMediaAssetModel)
                .join(
                    MyPhotoMediaAssetModel,
                    and_(
                        MyPhotoMediaAssetModel.id
                        == MyPhotoDeliveryAuthorizationModel.media_asset_id,
                        MyPhotoMediaAssetModel.agency_id
                        == MyPhotoDeliveryAuthorizationModel.agency_id,
                        MyPhotoMediaAssetModel.group_id
                        == MyPhotoDeliveryAuthorizationModel.group_id,
                    ),
                )
                .where(
                    MyPhotoDeliveryAuthorizationModel.id == authorization_id,
                    MyPhotoDeliveryAuthorizationModel.passenger_identity_id == identity.id,
                    MyPhotoDeliveryAuthorizationModel.agency_id == claims.agency_id,
                    MyPhotoDeliveryAuthorizationModel.group_id == trip.group.id,
                    MyPhotoDeliveryAuthorizationModel.status == "available",
                    MyPhotoDeliveryAuthorizationModel.transport == "development_fixture",
                )
            )
        ).first()
        if row is None:
            raise EntityNotFoundError("Photo delivery", authorization_id)
        authorization, asset = row
        if authorization.expires_at is None or _as_utc(authorization.expires_at) <= datetime.now(
            tz=UTC
        ):
            authorization.status = "expired"
            self._clear_delivery_metadata(authorization)
            authorization.stable_error_code = "DELIVERY_AUTHORIZATION_EXPIRED"
            await self._session.flush()
            raise MyPhotosUnavailable(
                "MY_PHOTOS_DELIVERY_EXPIRED", "Photo download authorization expired."
            )
        variant = "original" if authorization.quality == "original" else "optimized"
        content = synthetic_png(asset.immutable_asset_key, variant)
        checksum = hashlib.sha256(content).hexdigest()
        if (
            len(content) != authorization.expected_size_bytes
            or checksum != authorization.checksum_sha256
            or authorization.content_type != "image/png"
        ):
            authorization.status = "failed"
            self._clear_delivery_metadata(authorization)
            authorization.stable_error_code = "DELIVERY_INTEGRITY_FAILED"
            await self._session.flush()
            raise MyPhotosUnavailable(
                "MY_PHOTOS_DELIVERY_INTEGRITY_FAILED", "Photo delivery failed integrity checks."
            )
        return content, authorization.content_type, checksum

    async def production_download_location(
        self,
        *,
        claims: MobileAccessClaims,
        trip: AuthorizedMobileTrip,
        authorization_id: uuid.UUID,
    ) -> DeliveryResolution:
        """Resolve an authenticated opaque grant to a fresh, unpersisted URL."""

        identity = self._require_passenger(claims, trip)
        if self._providers.provider_name != "aws":
            raise EntityNotFoundError("Photo delivery", authorization_id)
        await self._ready_gallery(claims.agency_id, trip.group.id)
        row = (
            await self._session.execute(
                select(MyPhotoDeliveryAuthorizationModel, MyPhotoMediaAssetModel)
                .join(
                    MyPhotoMediaAssetModel,
                    and_(
                        MyPhotoMediaAssetModel.id
                        == MyPhotoDeliveryAuthorizationModel.media_asset_id,
                        MyPhotoMediaAssetModel.agency_id
                        == MyPhotoDeliveryAuthorizationModel.agency_id,
                        MyPhotoMediaAssetModel.group_id
                        == MyPhotoDeliveryAuthorizationModel.group_id,
                    ),
                )
                .where(
                    MyPhotoDeliveryAuthorizationModel.id == authorization_id,
                    MyPhotoDeliveryAuthorizationModel.passenger_identity_id == identity.id,
                    MyPhotoDeliveryAuthorizationModel.agency_id == claims.agency_id,
                    MyPhotoDeliveryAuthorizationModel.group_id == trip.group.id,
                    MyPhotoDeliveryAuthorizationModel.status == "available",
                    MyPhotoDeliveryAuthorizationModel.transport == "direct_object_storage",
                )
            )
        ).first()
        if row is None:
            raise EntityNotFoundError("Photo delivery", authorization_id)
        authorization, asset = row
        now = datetime.now(tz=UTC)
        if authorization.expires_at is None or _as_utc(authorization.expires_at) <= now:
            authorization.status = "expired"
            self._clear_delivery_metadata(authorization)
            authorization.stable_error_code = "DELIVERY_AUTHORIZATION_EXPIRED"
            await self._session.flush()
            raise MyPhotosUnavailable(
                "MY_PHOTOS_DELIVERY_EXPIRED", "Photo download authorization expired."
            )
        if (
            authorization.provider_authorization_reference is None
            or authorization.expected_size_bytes is None
            or authorization.checksum_sha256 is None
            or authorization.content_type not in _SUPPORTED_DELIVERY_MIME
        ):
            raise MyPhotosUnavailable(
                "MY_PHOTOS_DELIVERY_AUTHORIZATION_INVALID",
                "Photo download authorization is invalid.",
            )

        if authorization.quality == "optimized":
            optimized = (
                await self.latest_optimized_variants(
                    [asset.id],
                    agency_id=claims.agency_id,
                    group_id=trip.group.id,
                )
            ).get(asset.id)
            media_reference = optimized.storage_reference if optimized is not None else None
            source_size = optimized.byte_size if optimized is not None else None
            source_checksum = optimized.checksum_sha256 if optimized is not None else None
            source_content_type = optimized.mime_type if optimized is not None else None
        else:
            media_reference = asset.storage_reference
            source_size = asset.byte_size
            source_checksum = asset.checksum_sha256
            source_content_type = asset.mime_type
        if (
            media_reference is None
            or source_size != authorization.expected_size_bytes
            or source_checksum != authorization.checksum_sha256
            or source_content_type != authorization.content_type
        ):
            raise MyPhotosUnavailable(
                "MY_PHOTOS_DELIVERY_INTEGRITY_FAILED",
                "Photo delivery failed integrity checks.",
            )
        try:
            async with asyncio.timeout(self._settings.my_photos.media_provider_timeout_seconds):
                resolution = await self._providers.media.resolve(
                    DeliveryResolutionRequest(
                        tenant_scope=str(claims.agency_id),
                        group_scope=str(trip.group.id),
                        passenger_scope=str(identity.id),
                        authorization_identity=_authorization_identity(
                            authorization.id,
                            authorization.delivery_version,
                        ),
                        asset_identity=asset.immutable_asset_key,
                        media_reference=media_reference,
                        provider_authorization_reference=(
                            authorization.provider_authorization_reference
                        ),
                        quality=cast("Literal['original', 'optimized']", authorization.quality),
                        expected_size_bytes=authorization.expected_size_bytes,
                        checksum_sha256=authorization.checksum_sha256,
                        content_type=cast(
                            "Literal['image/jpeg', 'image/png', 'image/webp']",
                            authorization.content_type,
                        ),
                        expires_at=_as_utc(authorization.expires_at),
                    )
                )
        except MyPhotosUnavailable:
            raise
        except Exception as exc:
            raise MyPhotosUnavailable(
                "MY_PHOTOS_PROVIDER_UNAVAILABLE",
                "Photo delivery is temporarily unavailable.",
            ) from exc
        if (
            not resolution.location.startswith("https://")
            or not resolution.supports_ranges
            or _as_utc(resolution.expires_at) <= now
            or _as_utc(resolution.expires_at) > _as_utc(authorization.expires_at)
        ):
            raise MyPhotosUnavailable(
                "MY_PHOTOS_DELIVERY_AUTHORIZATION_INVALID",
                "Photo download authorization is invalid.",
            )
        return resolution

    async def development_preview_content(
        self,
        *,
        claims: MobileAccessClaims,
        trip: AuthorizedMobileTrip,
        asset_id: uuid.UUID,
        variant: str,
    ) -> tuple[bytes, str]:
        identity = self._require_passenger(claims, trip)
        if variant not in {"thumbnail", "preview"}:
            raise EntityNotFoundError("Photo preview", asset_id)
        if (
            self._settings.app_env != "development"
            or self._providers.provider_name != "development"
            or not self._settings.my_photos.development_fixtures_enabled
        ):
            raise EntityNotFoundError("Photo preview", asset_id)
        gallery = await self._ready_gallery(claims.agency_id, trip.group.id)
        asset = (await self._authorized_assets(identity.id, gallery, [asset_id])).get(asset_id)
        if asset is None:
            raise EntityNotFoundError("Photo preview", asset_id)
        content = synthetic_png(
            asset.immutable_asset_key,
            "thumbnail" if variant == "thumbnail" else "preview",
        )
        return content, hashlib.sha256(content).hexdigest()

    async def production_preview_location(
        self,
        *,
        claims: MobileAccessClaims,
        trip: AuthorizedMobileTrip,
        asset_id: uuid.UUID,
        variant: Literal["thumbnail", "preview"],
    ) -> DeliveryResolution:
        """Resolve a passenger-authorized preview to a fresh S3 location."""

        identity = self._require_passenger(claims, trip)
        if self._providers.provider_name != "aws":
            raise EntityNotFoundError("Photo preview", asset_id)
        gallery = await self._ready_gallery(claims.agency_id, trip.group.id)
        asset = (await self._authorized_assets(identity.id, gallery, [asset_id])).get(asset_id)
        if asset is None:
            raise EntityNotFoundError("Photo preview", asset_id)
        media_variant = (
            await self.latest_variants(
                [asset.id],
                agency_id=claims.agency_id,
                group_id=trip.group.id,
                variant_kinds=(variant,),
            )
        ).get((asset.id, variant))
        if not _preview_variant_is_downloadable(media_variant, asset, expected_kind=variant):
            raise EntityNotFoundError("Photo preview", asset_id)
        assert media_variant is not None
        assert media_variant.storage_reference is not None
        content_type = cast(
            "Literal['image/jpeg', 'image/png', 'image/webp']", media_variant.mime_type
        )
        authorization_identity = f"preview:{asset.id}:{variant}:{media_variant.delivery_version}"
        try:
            async with asyncio.timeout(self._settings.my_photos.media_provider_timeout_seconds):
                authorization = await self._providers.media.authorize(
                    DeliveryRequest(
                        tenant_scope=str(claims.agency_id),
                        group_scope=str(trip.group.id),
                        passenger_scope=str(identity.id),
                        authorization_identity=authorization_identity,
                        asset_identity=asset.immutable_asset_key,
                        media_reference=media_variant.storage_reference,
                        quality=variant,
                        availability_state=cast(
                            MediaAvailability, media_variant.availability_state
                        ),
                        expected_size_bytes=media_variant.byte_size,
                        checksum_sha256=media_variant.checksum_sha256,
                        content_type=content_type,
                    )
                )
                if (
                    authorization.transport != "direct_object_storage"
                    or authorization.provider_authorization_reference is None
                    or authorization.expected_size_bytes != media_variant.byte_size
                    or authorization.checksum_sha256 != media_variant.checksum_sha256
                    or authorization.content_type != content_type
                    or authorization.expires_at is None
                    or not authorization.supports_ranges
                ):
                    raise MyPhotosUnavailable(
                        "MY_PHOTOS_DELIVERY_AUTHORIZATION_INVALID",
                        "Photo preview authorization is invalid.",
                    )
                resolution = await self._providers.media.resolve(
                    DeliveryResolutionRequest(
                        tenant_scope=str(claims.agency_id),
                        group_scope=str(trip.group.id),
                        passenger_scope=str(identity.id),
                        authorization_identity=authorization_identity,
                        asset_identity=asset.immutable_asset_key,
                        media_reference=media_variant.storage_reference,
                        provider_authorization_reference=(
                            authorization.provider_authorization_reference
                        ),
                        quality=variant,
                        expected_size_bytes=media_variant.byte_size,
                        checksum_sha256=media_variant.checksum_sha256,
                        content_type=content_type,
                        expires_at=_as_utc(authorization.expires_at),
                    )
                )
        except MyPhotosUnavailable:
            raise
        except Exception as exc:
            raise MyPhotosUnavailable(
                "MY_PHOTOS_PROVIDER_UNAVAILABLE",
                "Photo preview is temporarily unavailable.",
            ) from exc
        now = datetime.now(tz=UTC)
        if (
            not resolution.location.startswith("https://")
            or not resolution.supports_ranges
            or _as_utc(resolution.expires_at) <= now
            or _as_utc(resolution.expires_at) > _as_utc(authorization.expires_at)
        ):
            raise MyPhotosUnavailable(
                "MY_PHOTOS_DELIVERY_AUTHORIZATION_INVALID",
                "Photo preview authorization is invalid.",
            )
        return resolution

    async def preview_content_or_location(
        self,
        *,
        claims: MobileAccessClaims,
        trip: AuthorizedMobileTrip,
        asset_id: uuid.UUID,
        variant: Literal["thumbnail", "preview"],
    ) -> tuple[bytes, str] | DeliveryResolution:
        if self._providers.provider_name == "aws":
            return await self.production_preview_location(
                claims=claims,
                trip=trip,
                asset_id=asset_id,
                variant=variant,
            )
        return await self.development_preview_content(
            claims=claims,
            trip=trip,
            asset_id=asset_id,
            variant=variant,
        )

    def photo_response(
        self,
        *,
        gallery: MyPhotoGalleryModel,
        group_id: uuid.UUID,
        account_cache_scope: str,
        match: MyPhotoMatchModel | None,
        asset: MyPhotoMediaAssetModel,
        thumbnail_variant: MyPhotoAssetVariantModel | None,
        preview_variant: MyPhotoAssetVariantModel | None,
        optimized_variant: MyPhotoAssetVariantModel | None,
    ) -> MyPhotosPhotoResponse:
        unavailable = (
            asset.availability_state in {"removed", "failed"} or asset.processing_state == "removed"
        )
        fixture_transport = (
            self._settings.app_env == "development"
            and self._settings.my_photos.development_fixtures_enabled
            and gallery.provider_name == "development"
            and not unavailable
        )
        missing_variant_state = (
            asset.availability_state
            if unavailable
            else "processing"
            if asset.processing_state == "processing"
            else "registered"
        )
        thumbnail_state = (
            "preview_available"
            if fixture_transport
            else thumbnail_variant.availability_state
            if thumbnail_variant is not None
            else missing_variant_state
        )
        preview_state = (
            "preview_available"
            if fixture_transport
            else preview_variant.availability_state
            if preview_variant is not None
            else missing_variant_state
        )
        production_transport = (
            self._providers.provider_name == "aws" and gallery.provider_name == "aws"
        )
        thumbnail_available = production_transport and _preview_variant_is_downloadable(
            thumbnail_variant, asset, expected_kind="thumbnail"
        )
        preview_available = production_transport and _preview_variant_is_downloadable(
            preview_variant, asset, expected_kind="preview"
        )
        thumbnail_path = (
            f"/api/v1/mobile/trips/{group_id}/my-photos/photos/{asset.id}/content/thumbnail"
            if fixture_transport or thumbnail_available
            else None
        )
        preview_path = (
            f"/api/v1/mobile/trips/{group_id}/my-photos/photos/{asset.id}/content/preview"
            if fixture_transport or preview_available
            else None
        )
        thumbnail_transport: Literal["authenticated_api", "unavailable"] = (
            "authenticated_api" if thumbnail_path is not None else "unavailable"
        )
        preview_transport: Literal["authenticated_api", "unavailable"] = (
            "authenticated_api" if preview_path is not None else "unavailable"
        )
        original_size = asset.byte_size
        original_checksum = asset.checksum_sha256
        if fixture_transport:
            content = synthetic_png(asset.immutable_asset_key, "original")
            original_size = len(content)
            original_checksum = hashlib.sha256(content).hexdigest()
        download_qualities: list[Literal["original", "optimized"]] = []
        if not unavailable:
            original_supported = bool(
                asset.mime_type in _SUPPORTED_DELIVERY_MIME
                and asset.processing_state != "removed"
                and asset.availability_state not in {"failed", "removed"}
                and (asset.archive_reference is not None or asset.storage_reference is not None)
            )
            if original_supported:
                download_qualities.append("original")
            if original_supported and _optimized_variant_is_downloadable(
                optimized_variant,
                asset,
            ):
                download_qualities.append("optimized")
        return MyPhotosPhotoResponse(
            asset_id=asset.id,
            match_id=match.id if match is not None else None,
            tier=match.display_tier if match is not None else None,  # type: ignore[arg-type]
            feedback=match.feedback if match is not None else "none",  # type: ignore[arg-type]
            width=asset.width,
            height=asset.height,
            aspect_ratio=asset.aspect_ratio,
            captured_at=asset.captured_at,
            thumbnail_state=thumbnail_state,  # type: ignore[arg-type]
            preview_state=preview_state,  # type: ignore[arg-type]
            original_state=asset.availability_state,  # type: ignore[arg-type]
            availability_state=asset.availability_state,  # type: ignore[arg-type]
            thumbnail=MyPhotosMediaDescriptor(
                state=thumbnail_state,  # type: ignore[arg-type]
                transport=thumbnail_transport,
                cache_key=(
                    f"myphotos:{account_cache_scope}:{gallery.published_revision}:"
                    f"{asset.id.hex}:thumbnail:"
                    f"{thumbnail_variant.delivery_version if thumbnail_variant else 0}"
                ),
                max_width=min(thumbnail_variant.width, 4_096) if thumbnail_variant else 240,
                max_height=(min(thumbnail_variant.height, 4_096) if thumbnail_variant else 180),
                resource_path=thumbnail_path,
                authorization_id=None,
                expires_at=None,
            ),
            preview=MyPhotosMediaDescriptor(
                state=preview_state,  # type: ignore[arg-type]
                transport=preview_transport,
                cache_key=(
                    f"myphotos:{account_cache_scope}:{gallery.published_revision}:"
                    f"{asset.id.hex}:preview:"
                    f"{preview_variant.delivery_version if preview_variant else 0}"
                ),
                max_width=min(preview_variant.width, 4_096) if preview_variant else 800,
                max_height=min(preview_variant.height, 4_096) if preview_variant else 600,
                resource_path=preview_path,
                authorization_id=None,
                expires_at=None,
            ),
            download_qualities=download_qualities,
            original_byte_size=original_size,
            original_checksum_sha256=original_checksum,
            preparing=asset.availability_state in MEDIA_PREPARING_STATES,
        )

    def _delivery_response_item(
        self,
        *,
        group_id: uuid.UUID,
        authorization: MyPhotoDeliveryAuthorizationModel,
        transport: str,
        retry_after_seconds: int | None,
    ) -> MyPhotosDownloadAuthorizationItemResponse:
        available = authorization.status == "available"
        response_state: Literal["available", "preparing", "unavailable"] = (
            "available"
            if available
            else "preparing"
            if authorization.status in {"authorizing", "preparing"}
            else "unavailable"
        )
        resource_path = (
            f"/api/v1/mobile/trips/{group_id}/my-photos/download-authorizations/"
            f"{authorization.id}/content"
            if available and transport == "development_fixture"
            else None
        )
        return MyPhotosDownloadAuthorizationItemResponse(
            asset_id=authorization.media_asset_id,
            authorization_id=authorization.id if available else None,
            quality=authorization.quality,  # type: ignore[arg-type]
            delivery_version=authorization.delivery_version,
            state=response_state,
            transport=transport,  # type: ignore[arg-type]
            expected_size_bytes=authorization.expected_size_bytes,
            checksum_sha256=authorization.checksum_sha256,
            supports_ranges=authorization.supports_ranges,
            expires_at=authorization.expires_at,
            retry_after_seconds=retry_after_seconds,
            content_type=authorization.content_type,  # type: ignore[arg-type]
            resource_path=resource_path,
        )

    @staticmethod
    def _clear_delivery_metadata(
        authorization: MyPhotoDeliveryAuthorizationModel,
    ) -> None:
        authorization.provider_authorization_reference = None
        authorization.transport = "unavailable"
        authorization.expected_size_bytes = None
        authorization.checksum_sha256 = None
        authorization.content_type = None
        authorization.supports_ranges = False
        authorization.expires_at = None
        authorization.stable_error_code = None

    async def _finalize_delivery_claims(
        self,
        results: list[tuple[uuid.UUID, str, DeliveryAuthorization | None, str | None]],
    ) -> None:
        if not results:
            return
        rows = list(
            (
                await self._session.execute(
                    select(MyPhotoDeliveryAuthorizationModel)
                    .where(
                        MyPhotoDeliveryAuthorizationModel.id.in_(tuple(item[0] for item in results))
                    )
                    .with_for_update()
                )
            ).scalars()
        )
        by_id = {row.id: row for row in rows}
        now = datetime.now(tz=UTC)
        for authorization_id, claim_token, provider_result, error_code in results:
            row = by_id.get(authorization_id)
            if row is None or row.status != "authorizing" or row.claim_token != claim_token:
                continue
            row.claim_token = None
            row.claim_expires_at = None
            if error_code is not None or provider_result is None:
                row.status = "failed"
                row.stable_error_code = error_code or "DELIVERY_PROVIDER_UNAVAILABLE"
                self._clear_delivery_metadata(row)
                row.stable_error_code = error_code or "DELIVERY_PROVIDER_UNAVAILABLE"
                continue
            available = provider_result.state == "delivery_available"
            complete = (
                provider_result.provider_authorization_reference is not None
                and provider_result.expected_size_bytes is not None
                and provider_result.checksum_sha256 is not None
                and provider_result.content_type is not None
                and provider_result.expires_at is not None
                and _as_utc(provider_result.expires_at) > now
                and provider_result.transport != "unavailable"
            )
            if available and not complete:
                row.status = "failed"
                self._clear_delivery_metadata(row)
                row.stable_error_code = "DELIVERY_PROVIDER_INVALID"
                continue
            if not available:
                row.status = "preparing"
                self._clear_delivery_metadata(row)
                continue
            row.status = "available"
            row.provider_authorization_reference = provider_result.provider_authorization_reference
            row.transport = provider_result.transport
            row.expected_size_bytes = provider_result.expected_size_bytes
            row.checksum_sha256 = provider_result.checksum_sha256
            row.content_type = provider_result.content_type
            row.supports_ranges = provider_result.supports_ranges
            row.expires_at = provider_result.expires_at
            row.stable_error_code = None
        await self._session.flush()

    async def _authorized_assets(
        self,
        passenger_identity_id: uuid.UUID,
        gallery: MyPhotoGalleryModel,
        asset_ids: list[uuid.UUID],
    ) -> dict[uuid.UUID, MyPhotoMediaAssetModel]:
        requested = set(asset_ids)
        assets = list(
            (
                await self._session.execute(
                    select(MyPhotoMediaAssetModel).where(
                        MyPhotoMediaAssetModel.id.in_(tuple(requested)),
                        MyPhotoMediaAssetModel.gallery_id == gallery.id,
                        MyPhotoMediaAssetModel.agency_id == gallery.agency_id,
                        MyPhotoMediaAssetModel.group_id == gallery.group_id,
                        MyPhotoMediaAssetModel.published_revision <= gallery.published_revision,
                        MyPhotoMediaAssetModel.processing_state != "removed",
                        MyPhotoMediaAssetModel.availability_state.notin_(("failed", "removed")),
                    )
                )
            ).scalars()
        )
        by_id = {asset.id: asset for asset in assets}
        if gallery.all_group_photos_enabled:
            return by_id
        matched_ids = set(
            (
                await self._session.execute(
                    select(MyPhotoMatchModel.media_asset_id).where(
                        MyPhotoMatchModel.passenger_identity_id == passenger_identity_id,
                        MyPhotoMatchModel.group_id == gallery.group_id,
                        MyPhotoMatchModel.gallery_revision <= gallery.published_revision,
                        MyPhotoMatchModel.active.is_(True),
                        MyPhotoMatchModel.media_asset_id.in_(tuple(requested)),
                    )
                )
            ).scalars()
        )
        return {asset_id: asset for asset_id, asset in by_id.items() if asset_id in matched_ids}

    async def latest_optimized_variants(
        self,
        asset_ids: list[uuid.UUID],
        *,
        agency_id: uuid.UUID,
        group_id: uuid.UUID,
    ) -> dict[uuid.UUID, MyPhotoAssetVariantModel]:
        variants = await self.latest_variants(
            asset_ids,
            agency_id=agency_id,
            group_id=group_id,
            variant_kinds=("optimized",),
        )
        return {
            asset_id: row
            for (asset_id, variant_kind), row in variants.items()
            if variant_kind == "optimized"
        }

    async def latest_variants(
        self,
        asset_ids: list[uuid.UUID],
        *,
        agency_id: uuid.UUID,
        group_id: uuid.UUID,
        variant_kinds: tuple[str, ...],
    ) -> dict[tuple[uuid.UUID, str], MyPhotoAssetVariantModel]:
        """Load latest bounded display/delivery variants in one query."""

        requested = tuple(set(asset_ids))
        if not requested:
            return {}
        if not variant_kinds or not set(variant_kinds) <= {
            "thumbnail",
            "preview",
            "analysis",
            "original",
            "optimized",
        }:
            raise ValueError("Unsupported My Photos variant kind")
        latest = (
            select(
                MyPhotoAssetVariantModel.media_asset_id.label("asset_id"),
                MyPhotoAssetVariantModel.variant_kind.label("variant_kind"),
                func.max(MyPhotoAssetVariantModel.delivery_version).label("delivery_version"),
            )
            .where(
                MyPhotoAssetVariantModel.media_asset_id.in_(requested),
                MyPhotoAssetVariantModel.agency_id == agency_id,
                MyPhotoAssetVariantModel.group_id == group_id,
                MyPhotoAssetVariantModel.variant_kind.in_(variant_kinds),
                MyPhotoAssetVariantModel.availability_state.notin_(("failed", "removed")),
            )
            .group_by(
                MyPhotoAssetVariantModel.media_asset_id,
                MyPhotoAssetVariantModel.variant_kind,
            )
            .subquery()
        )
        rows = list(
            (
                await self._session.execute(
                    select(MyPhotoAssetVariantModel).join(
                        latest,
                        and_(
                            latest.c.asset_id == MyPhotoAssetVariantModel.media_asset_id,
                            latest.c.delivery_version == MyPhotoAssetVariantModel.delivery_version,
                            latest.c.variant_kind == MyPhotoAssetVariantModel.variant_kind,
                        ),
                    )
                )
            ).scalars()
        )
        return {(row.media_asset_id, row.variant_kind): row for row in rows}


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _optimized_variant_is_downloadable(
    variant: MyPhotoAssetVariantModel | None,
    asset: MyPhotoMediaAssetModel,
    *,
    now: datetime | None = None,
) -> bool:
    """Use one fail-closed predicate for gallery advertisement and authorization."""

    if variant is None:
        return False
    effective_now = now or datetime.now(tz=UTC)
    return bool(
        variant.storage_reference
        and "://" not in variant.storage_reference
        and variant.mime_type in _SUPPORTED_DELIVERY_MIME
        and 0 < variant.byte_size <= asset.byte_size
        and variant.availability_state in MEDIA_DELIVERY_READY_STATES
        and (variant.expires_at is None or _as_utc(variant.expires_at) > effective_now)
    )


def _preview_variant_is_downloadable(
    media_variant: MyPhotoAssetVariantModel | None,
    asset: MyPhotoMediaAssetModel,
    *,
    expected_kind: Literal["thumbnail", "preview"],
    now: datetime | None = None,
) -> bool:
    effective_now = now or datetime.now(tz=UTC)
    return bool(
        media_variant is not None
        and media_variant.variant_kind == expected_kind
        and media_variant.storage_reference is not None
        and "://" not in media_variant.storage_reference
        and media_variant.mime_type in _SUPPORTED_DELIVERY_MIME
        and media_variant.byte_size > 0
        and len(media_variant.checksum_sha256) == 64
        and media_variant.availability_state in MEDIA_DELIVERY_READY_STATES
        and (media_variant.expires_at is None or _as_utc(media_variant.expires_at) > effective_now)
        and asset.processing_state != "removed"
        and asset.availability_state not in {"failed", "removed"}
    )


def _content_version(
    *,
    quality: str,
    optimized_variant: MyPhotoAssetVariantModel | None,
) -> int:
    if quality == "original":
        # Original media assets are immutable. A replacement is a new asset,
        # therefore V1 is stable across short-lived grant refreshes.
        return 1
    if quality == "optimized" and optimized_variant is not None:
        return int(optimized_variant.delivery_version)
    raise ValueError("optimized content version is unavailable")


def _delivery_request_fingerprint(
    request: MyPhotosDownloadAuthorizationRequest,
    versions: dict[tuple[uuid.UUID, str], int],
) -> str:
    body = "|".join(
        sorted(
            f"{item.asset_id}:{item.quality}:{versions[(item.asset_id, item.quality)]}"
            for item in request.items
        )
    )
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _authorization_identity(authorization_id: uuid.UUID, content_version: int) -> str:
    return f"{authorization_id}:{content_version}"


async def _authorize_provider_batch(
    *,
    provider: MediaDeliveryProvider,
    pending_calls: tuple[tuple[uuid.UUID, str, DeliveryRequest], ...],
    maximum_ttl_seconds: int,
    timeout_seconds: int,
    concurrency: int,
    maximum_batch_size: int,
) -> tuple[tuple[uuid.UUID, str, DeliveryAuthorization | None, str | None], ...]:
    """Authorize one protocol-bounded batch with conservative concurrency.

    ``asyncio.gather`` preserves the input order. The semaphore bounds active
    provider calls, while the explicit maximum prevents this internal helper
    from ever becoming an unbounded fan-out if a future caller bypasses the API
    schema and service limit.
    """

    if not 1 <= concurrency <= 8:
        raise ValueError("Invalid delivery authorization concurrency")
    if len(pending_calls) > maximum_batch_size or not 1 <= maximum_batch_size <= 100:
        raise ValueError("Unbounded delivery authorization batch")
    semaphore = asyncio.Semaphore(concurrency)

    async def authorize_one(
        pending: tuple[uuid.UUID, str, DeliveryRequest],
    ) -> tuple[uuid.UUID, str, DeliveryAuthorization | None, str | None]:
        authorization_id, claim_token, request = pending
        async with semaphore:
            result, error_code = await _safe_provider_authorize(
                provider,
                request,
                maximum_ttl_seconds=maximum_ttl_seconds,
                timeout_seconds=timeout_seconds,
            )
        return authorization_id, claim_token, result, error_code

    return tuple(await asyncio.gather(*(authorize_one(pending) for pending in pending_calls)))


async def _safe_provider_authorize(
    provider: MediaDeliveryProvider,
    request: DeliveryRequest,
    *,
    maximum_ttl_seconds: int,
    timeout_seconds: int,
) -> tuple[DeliveryAuthorization | None, str | None]:
    try:
        async with asyncio.timeout(timeout_seconds):
            result = await provider.authorize(request)
        return (
            _validated_delivery_authorization(
                result,
                request,
                maximum_ttl_seconds=maximum_ttl_seconds,
            ),
            None,
        )
    except MyPhotosUnavailable as exc:
        return None, _stable_error_code(exc.code)
    except Exception:
        # Never persist or surface raw adapter/network errors after a durable
        # claim. The caller finalizes the claim to this stable failure category.
        my_photos_metrics.provider("unavailable")
        return None, "DELIVERY_PROVIDER_UNAVAILABLE"


def _validated_delivery_authorization(
    result: DeliveryAuthorization,
    request: DeliveryRequest,
    *,
    maximum_ttl_seconds: int,
) -> DeliveryAuthorization:
    allowed_states = {
        "registered",
        "awaiting_upload",
        "processing",
        "indexed",
        "preview_available",
        "original_available_online",
        "archived_offline",
        "rehydration_requested",
        "preparing_delivery",
        "delivery_available",
        "expired",
        "failed",
        "removed",
    }
    if result.state not in allowed_states:
        raise ValueError("Invalid media provider state")
    if result.state != "delivery_available":
        if (
            any(
                value is not None
                for value in (
                    result.provider_authorization_reference,
                    result.expected_size_bytes,
                    result.checksum_sha256,
                    result.expires_at,
                    result.content_type,
                )
            )
            or result.transport != "unavailable"
        ):
            raise ValueError("Unavailable media authorization carried delivery data")
        return result
    reference = result.provider_authorization_reference
    checksum = result.checksum_sha256
    expiry = result.expires_at
    if not (
        reference
        and len(reference) <= 512
        and reference == reference.strip()
        and reference.isprintable()
        and "://" not in reference
    ):
        raise ValueError("Invalid media provider authorization reference")
    if (
        result.expected_size_bytes != request.expected_size_bytes
        or checksum != request.checksum_sha256
        or checksum is None
        or len(checksum) != 64
        or checksum != checksum.lower()
        or any(character not in "0123456789abcdef" for character in checksum)
    ):
        raise ValueError("Media provider integrity metadata changed")
    if result.content_type not in _SUPPORTED_DELIVERY_MIME:
        raise ValueError("Invalid media provider content type")
    if result.content_type != request.content_type:
        raise ValueError("Media provider content type changed")
    if result.transport not in {"development_fixture", "direct_object_storage"}:
        raise ValueError("Invalid media provider transport")
    now = datetime.now(tz=UTC)
    if (
        expiry is None
        or _as_utc(expiry) <= now
        or _as_utc(expiry) > now + timedelta(seconds=maximum_ttl_seconds)
    ):
        raise ValueError("Expired media provider authorization")
    return result


def _stable_error_code(value: str) -> str:
    normalized = "".join(
        character if character.isascii() and (character.isalnum() or character == "_") else "_"
        for character in value.upper()
    ).strip("_")
    return (normalized or "DELIVERY_PROVIDER_UNAVAILABLE")[:64]


__all__ = ["MyPhotosDeliveryService"]
