"""Private photo previews operations."""

from __future__ import annotations

import asyncio
import hashlib
import uuid
from datetime import UTC, datetime
from typing import Literal, cast

from app.application.my_photos.errors import MyPhotosUnavailable
from app.application.my_photos.providers import (
    DeliveryRequest,
    DeliveryResolution,
    DeliveryResolutionRequest,
)
from app.application.my_photos.states import (
    MediaAvailability,
)
from app.application.security.mobile_access_policy import AuthorizedMobileTrip
from app.core.security.mobile_jwt import MobileAccessClaims
from app.domain.exceptions.exceptions import EntityNotFoundError
from app.infrastructure.my_photos.delivery_assets import (
    MyPhotosDeliveryAssets,
)
from app.infrastructure.my_photos.delivery_context import (
    MyPhotosDeliveryContext,
)
from app.infrastructure.my_photos.delivery_policy import (
    _as_utc,
    _delivery_deadline,
    _preview_variant_is_downloadable,
)
from app.infrastructure.my_photos.synthetic_media import synthetic_png


class MyPhotosPreviewContent:
    def __init__(self, context: MyPhotosDeliveryContext, assets: MyPhotosDeliveryAssets) -> None:
        self._context = context
        self._assets = assets

    async def development_preview_content(
        self,
        *,
        claims: MobileAccessClaims,
        trip: AuthorizedMobileTrip,
        asset_id: uuid.UUID,
        variant: str,
    ) -> tuple[bytes, str]:
        identity = self._context.require_passenger(claims, trip)
        if variant not in {"thumbnail", "preview"}:
            raise EntityNotFoundError("Photo preview", asset_id)
        if (
            self._context.settings.app_env != "development"
            or self._context.providers.provider_name != "development"
            or not self._context.settings.my_photos.development_fixtures_enabled
        ):
            raise EntityNotFoundError("Photo preview", asset_id)
        gallery = await self._context.ready_gallery(claims.agency_id, trip.group.id)
        asset = (await self._assets._authorized_assets(identity.id, gallery, [asset_id])).get(
            asset_id
        )
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

        identity = self._context.require_passenger(claims, trip)
        if self._context.providers.provider_name != "aws":
            raise EntityNotFoundError("Photo preview", asset_id)
        gallery = await self._context.ready_gallery(claims.agency_id, trip.group.id)
        asset = (await self._assets._authorized_assets(identity.id, gallery, [asset_id])).get(
            asset_id
        )
        if asset is None:
            raise EntityNotFoundError("Photo preview", asset_id)
        media_variant = (
            await self._assets.latest_variants(
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
            async with asyncio.timeout(
                self._context.settings.my_photos.media_provider_timeout_seconds
            ):
                authorization = await self._context.providers.media.authorize(
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
                resolution = await self._context.providers.media.resolve(
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
                        expires_at=_delivery_deadline(
                            authorization.expires_at,
                            gallery,
                            content_expires_at=media_variant.expires_at,
                        ),
                    )
                )
        except MyPhotosUnavailable:
            raise
        except Exception as exc:
            raise MyPhotosUnavailable(
                "MY_PHOTOS_PROVIDER_UNAVAILABLE",
                "Photo preview is temporarily unavailable.",
            ) from exc
        current_gallery, _current_asset = await self._assets._current_delivery_asset(
            identity.id, claims.agency_id, trip.group.id, asset.id
        )
        now = datetime.now(tz=UTC)
        if (
            not resolution.location.startswith("https://")
            or not resolution.supports_ranges
            or _as_utc(resolution.expires_at) <= now
            or _as_utc(resolution.expires_at)
            > _delivery_deadline(authorization.expires_at, current_gallery)
        ):
            raise MyPhotosUnavailable(
                "MY_PHOTOS_DELIVERY_AUTHORIZATION_INVALID",
                "Photo preview authorization is invalid.",
            )
        return resolution
