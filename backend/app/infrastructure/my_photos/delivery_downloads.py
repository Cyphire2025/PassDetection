"""Private photo downloads operations."""

from __future__ import annotations

import asyncio
import hashlib
import uuid
from datetime import UTC, datetime
from typing import Literal, cast

from sqlalchemy import and_, select

from app.application.my_photos.errors import MyPhotosUnavailable
from app.application.my_photos.providers import (
    DeliveryResolution,
    DeliveryResolutionRequest,
)
from app.application.security.mobile_access_policy import AuthorizedMobileTrip
from app.core.security.mobile_jwt import MobileAccessClaims
from app.domain.exceptions.exceptions import EntityNotFoundError
from app.infrastructure.database.my_photos_models import (
    MyPhotoDeliveryAuthorizationModel,
    MyPhotoMediaAssetModel,
)
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
    _delivery_deadline,
)
from app.infrastructure.my_photos.delivery_projection import (
    _clear_delivery_metadata,
)
from app.infrastructure.my_photos.synthetic_media import synthetic_png


class MyPhotosDownloadContent:
    def __init__(self, context: MyPhotosDeliveryContext, assets: MyPhotosDeliveryAssets) -> None:
        self._context = context
        self._assets = assets

    async def development_download_content(
        self,
        *,
        claims: MobileAccessClaims,
        trip: AuthorizedMobileTrip,
        authorization_id: uuid.UUID,
    ) -> tuple[bytes, str, str]:
        identity = self._context.require_passenger(claims, trip)
        if (
            self._context.settings.app_env != "development"
            or self._context.providers.provider_name != "development"
        ):
            raise EntityNotFoundError("Photo delivery", authorization_id)
        await self._context.ready_gallery(claims.agency_id, trip.group.id)
        row = (
            await self._context.session.execute(
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
            _clear_delivery_metadata(authorization)
            authorization.stable_error_code = "DELIVERY_AUTHORIZATION_EXPIRED"
            await self._context.session.flush()
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
            _clear_delivery_metadata(authorization)
            authorization.stable_error_code = "DELIVERY_INTEGRITY_FAILED"
            await self._context.session.flush()
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

        identity = self._context.require_passenger(claims, trip)
        if self._context.providers.provider_name != "aws":
            raise EntityNotFoundError("Photo delivery", authorization_id)
        gallery = await self._context.ready_gallery(claims.agency_id, trip.group.id)
        row = (
            await self._context.session.execute(
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
            _clear_delivery_metadata(authorization)
            authorization.stable_error_code = "DELIVERY_AUTHORIZATION_EXPIRED"
            await self._context.session.flush()
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
                await self._assets.latest_optimized_variants(
                    [asset.id],
                    agency_id=claims.agency_id,
                    group_id=trip.group.id,
                )
            ).get(asset.id)
            media_reference = optimized.storage_reference if optimized is not None else None
            source_size = optimized.byte_size if optimized is not None else None
            source_checksum = optimized.checksum_sha256 if optimized is not None else None
            source_content_type = optimized.mime_type if optimized is not None else None
            source_expires_at = optimized.expires_at if optimized is not None else None
        else:
            media_reference = asset.storage_reference
            source_size = asset.byte_size
            source_checksum = asset.checksum_sha256
            source_content_type = asset.mime_type
            source_expires_at = None
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
        expected_grant = (
            authorization.provider_authorization_reference,
            authorization.delivery_version,
        )
        try:
            async with asyncio.timeout(
                self._context.settings.my_photos.media_provider_timeout_seconds
            ):
                resolution = await self._context.providers.media.resolve(
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
                        expires_at=_delivery_deadline(
                            authorization.expires_at, gallery, content_expires_at=source_expires_at
                        ),
                    )
                )
        except MyPhotosUnavailable:
            raise
        except Exception as exc:
            raise MyPhotosUnavailable(
                "MY_PHOTOS_PROVIDER_UNAVAILABLE",
                "Photo delivery is temporarily unavailable.",
            ) from exc
        current_gallery, _current_asset = await self._assets._current_delivery_asset(
            identity.id, claims.agency_id, trip.group.id, asset.id
        )
        current_grant = (
            await self._context.session.execute(
                select(MyPhotoDeliveryAuthorizationModel)
                .where(
                    MyPhotoDeliveryAuthorizationModel.id == authorization_id,
                    MyPhotoDeliveryAuthorizationModel.passenger_identity_id == identity.id,
                    MyPhotoDeliveryAuthorizationModel.agency_id == claims.agency_id,
                    MyPhotoDeliveryAuthorizationModel.group_id == trip.group.id,
                    MyPhotoDeliveryAuthorizationModel.status == "available",
                    MyPhotoDeliveryAuthorizationModel.expires_at > datetime.now(tz=UTC),
                )
                .execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()
        if (
            current_grant is None
            or (current_grant.provider_authorization_reference, current_grant.delivery_version)
            != expected_grant
        ):
            raise EntityNotFoundError("Photo delivery", authorization_id)
        assert current_grant.expires_at is not None
        now = datetime.now(tz=UTC)
        if (
            not resolution.location.startswith("https://")
            or not resolution.supports_ranges
            or _as_utc(resolution.expires_at) <= now
            or _as_utc(resolution.expires_at)
            > _delivery_deadline(current_grant.expires_at, current_gallery)
        ):
            raise MyPhotosUnavailable(
                "MY_PHOTOS_DELIVERY_AUTHORIZATION_INVALID",
                "Photo download authorization is invalid.",
            )
        return resolution
