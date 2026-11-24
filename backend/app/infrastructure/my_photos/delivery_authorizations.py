"""Private photo authorizations operations."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Literal, cast

from sqlalchemy import select

from app.application.my_photos.errors import MyPhotosConflict
from app.application.my_photos.providers import (
    DeliveryAuthorization,
    DeliveryRequest,
)
from app.application.my_photos.states import (
    MEDIA_DELIVERY_READY_STATES,
    MEDIA_PREPARING_STATES,
    MediaAvailability,
)
from app.application.security.mobile_access_policy import AuthorizedMobileTrip
from app.core.security.mobile_jwt import MobileAccessClaims
from app.domain.exceptions.exceptions import EntityNotFoundError
from app.infrastructure.database.my_photos_models import (
    MyPhotoDeliveryAuthorizationModel,
)
from app.infrastructure.my_photos.audit import record_my_photos_audit
from app.infrastructure.my_photos.delivery_assets import (
    MyPhotosDeliveryAssets,
)
from app.infrastructure.my_photos.delivery_context import (
    MyPhotosDeliveryContext,
)
from app.infrastructure.my_photos.delivery_policy import (
    _SUPPORTED_DELIVERY_MIME,
    _as_utc,
    _authorization_identity,
    _content_version,
    _delivery_request_fingerprint,
    _optimized_variant_is_downloadable,
)
from app.infrastructure.my_photos.delivery_projection import (
    _clear_delivery_metadata,
    _delivery_response_item,
)
from app.infrastructure.my_photos.delivery_provider import (
    _authorize_provider_batch,
)
from app.presentation.api.v1.schemas.my_photos_schemas import (
    MyPhotosDownloadAuthorizationRequest,
    MyPhotosDownloadAuthorizationResponse,
)


class MyPhotosDeliveryAuthorizations:
    def __init__(self, context: MyPhotosDeliveryContext, assets: MyPhotosDeliveryAssets) -> None:
        self._context = context
        self._assets = assets

    async def authorize_downloads(
        self,
        *,
        claims: MobileAccessClaims,
        trip: AuthorizedMobileTrip,
        request: MyPhotosDownloadAuthorizationRequest,
    ) -> MyPhotosDownloadAuthorizationResponse:
        identity = self._context.require_passenger(claims, trip)
        gallery = await self._context.ready_gallery(claims.agency_id, trip.group.id)
        await self._context.lock_passenger_identity(identity.id, claims.agency_id, trip.group.id)
        if len(request.items) > self._context.settings.my_photos.maximum_delivery_batch:
            raise MyPhotosConflict(
                "MY_PHOTOS_DOWNLOAD_BATCH_TOO_LARGE", "Too many photos were requested at once."
            )
        asset_ids = [item.asset_id for item in request.items]
        assets = await self._assets._authorized_assets(identity.id, gallery, asset_ids)
        if set(assets) != set(asset_ids):
            raise EntityNotFoundError("My Photos asset", "unavailable")
        optimized_variants = await self._assets.latest_optimized_variants(
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
                await self._context.session.execute(
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
                self._context.session.add(authorization)
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
                seconds=self._context.settings.my_photos.delivery_claim_seconds
            )
            _clear_delivery_metadata(authorization)
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
                            if self._context.providers.provider_name == "development"
                            else source_content_type,
                        ),
                    ),
                )
            )
        await self._context.session.flush()

        provider_results: list[tuple[uuid.UUID, str, DeliveryAuthorization | None, str | None]] = []
        if pending_calls:
            # Persist the claims and release the passenger/authorization locks
            # before bounded provider I/O. No URL or credential is stored here.
            await self._context.session.commit()
            provider_results = list(
                await _authorize_provider_batch(
                    provider=self._context.providers.media,
                    pending_calls=tuple(pending_calls),
                    maximum_ttl_seconds=(
                        self._context.settings.my_photos.delivery_authorization_ttl_seconds
                    ),
                    timeout_seconds=self._context.settings.my_photos.media_provider_timeout_seconds,
                    concurrency=self._context.settings.my_photos.delivery_authorization_concurrency,
                    maximum_batch_size=self._context.settings.my_photos.maximum_delivery_batch,
                )
            )
            gallery = await self._context.ready_gallery(claims.agency_id, trip.group.id)
            current_assets = await self._assets._authorized_assets(identity.id, gallery, asset_ids)
            if set(current_assets) != set(asset_ids):
                raise EntityNotFoundError("My Photos asset", "unavailable")
            await self._finalize_delivery_claims(
                provider_results, access_ends_at=gallery.availability_ends_at
            )

        refreshed_rows = list(
            (
                await self._context.session.execute(
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
                self._context.session,
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
                _delivery_response_item(
                    group_id=trip.group.id,
                    authorization=refreshed_by_item[(item.asset_id, item.quality)],
                    transport=refreshed_by_item[(item.asset_id, item.quality)].transport,
                    retry_after_seconds=(
                        self._context.settings.my_photos.provider_retry_after_seconds
                        if refreshed_by_item[(item.asset_id, item.quality)].status
                        in {"authorizing", "preparing", "failed"}
                        else None
                    ),
                )
                for item in request.items
            ]
        )

    async def _finalize_delivery_claims(
        self,
        results: list[tuple[uuid.UUID, str, DeliveryAuthorization | None, str | None]],
        *,
        access_ends_at: datetime | None = None,
    ) -> None:
        if not results:
            return
        rows = list(
            (
                await self._context.session.execute(
                    select(MyPhotoDeliveryAuthorizationModel)
                    .where(
                        MyPhotoDeliveryAuthorizationModel.id.in_(tuple(item[0] for item in results))
                    )
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
            ).scalars()
        )
        by_id = {row.id: row for row in rows}
        now = datetime.now(tz=UTC)
        for authorization_id, claim_token, provider_result, error_code in results:
            row = by_id.get(authorization_id)
            if (
                row is None
                or row.status != "authorizing"
                or row.claim_token != claim_token
                or row.claim_expires_at is None
                or _as_utc(row.claim_expires_at) <= now
            ):
                continue
            row.claim_token = None
            row.claim_expires_at = None
            if error_code is not None or provider_result is None:
                row.status = "failed"
                _clear_delivery_metadata(row)
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
                _clear_delivery_metadata(row)
                row.stable_error_code = "DELIVERY_PROVIDER_INVALID"
                continue
            if not available:
                row.status = "preparing"
                _clear_delivery_metadata(row)
                continue
            row.status = "available"
            row.provider_authorization_reference = provider_result.provider_authorization_reference
            row.transport = provider_result.transport
            row.expected_size_bytes = provider_result.expected_size_bytes
            row.checksum_sha256 = provider_result.checksum_sha256
            row.content_type = provider_result.content_type
            row.supports_ranges = provider_result.supports_ranges
            row.expires_at = (
                min(_as_utc(provider_result.expires_at), _as_utc(access_ends_at))
                if provider_result.expires_at is not None and access_ends_at is not None
                else provider_result.expires_at
            )
            row.stable_error_code = None
        await self._context.session.flush()
