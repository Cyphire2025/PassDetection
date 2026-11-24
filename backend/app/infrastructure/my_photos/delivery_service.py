"""Stable facade for focused private My Photos delivery owners."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.application.my_photos.providers import (
    DeliveryAuthorization,
    DeliveryResolution,
)
from app.application.security.mobile_access_policy import AuthorizedMobileTrip
from app.core.config.settings import Settings
from app.core.security.mobile_jwt import MobileAccessClaims
from app.infrastructure.database.my_photos_models import (
    MyPhotoAssetVariantModel,
    MyPhotoDeliveryAuthorizationModel,
    MyPhotoGalleryModel,
    MyPhotoMatchModel,
    MyPhotoMediaAssetModel,
)
from app.infrastructure.my_photos.delivery_assets import MyPhotosDeliveryAssets
from app.infrastructure.my_photos.delivery_authorizations import MyPhotosDeliveryAuthorizations
from app.infrastructure.my_photos.delivery_context import (
    GalleryResolver as GalleryResolver,
)
from app.infrastructure.my_photos.delivery_context import (
    MyPhotosDeliveryContext,
)
from app.infrastructure.my_photos.delivery_context import (
    PassengerLocker as PassengerLocker,
)
from app.infrastructure.my_photos.delivery_context import (
    PassengerResolver as PassengerResolver,
)
from app.infrastructure.my_photos.delivery_downloads import MyPhotosDownloadContent
from app.infrastructure.my_photos.delivery_plan import MyPhotosDownloadPlan
from app.infrastructure.my_photos.delivery_policy import (
    _SUPPORTED_DELIVERY_MIME as _SUPPORTED_DELIVERY_MIME,
)
from app.infrastructure.my_photos.delivery_policy import (
    _as_utc as _as_utc,
)
from app.infrastructure.my_photos.delivery_policy import (
    _authorization_identity as _authorization_identity,
)
from app.infrastructure.my_photos.delivery_policy import (
    _content_version as _content_version,
)
from app.infrastructure.my_photos.delivery_policy import (
    _delivery_deadline as _delivery_deadline,
)
from app.infrastructure.my_photos.delivery_policy import (
    _delivery_request_fingerprint as _delivery_request_fingerprint,
)
from app.infrastructure.my_photos.delivery_policy import (
    _optimized_variant_is_downloadable as _optimized_variant_is_downloadable,
)
from app.infrastructure.my_photos.delivery_policy import (
    _preview_variant_is_downloadable as _preview_variant_is_downloadable,
)
from app.infrastructure.my_photos.delivery_preparation import MyPhotosMediaPreparation
from app.infrastructure.my_photos.delivery_previews import MyPhotosPreviewContent
from app.infrastructure.my_photos.delivery_projection import (
    _clear_delivery_metadata,
    _delivery_response_item,
    photo_response,
)
from app.infrastructure.my_photos.delivery_provider import (
    _authorize_provider_batch as _authorize_provider_batch,
)
from app.infrastructure.my_photos.delivery_provider import (
    _safe_provider_authorize as _safe_provider_authorize,
)
from app.infrastructure.my_photos.delivery_provider import (
    _stable_error_code as _stable_error_code,
)
from app.infrastructure.my_photos.delivery_provider import (
    _validated_delivery_authorization as _validated_delivery_authorization,
)
from app.infrastructure.my_photos.providers import MyPhotosProviderBundle
from app.presentation.api.v1.schemas.my_photos_schemas import (
    MyPhotosDownloadAuthorizationItemResponse,
    MyPhotosDownloadAuthorizationRequest,
    MyPhotosDownloadAuthorizationResponse,
    MyPhotosDownloadPlanResponse,
    MyPhotosPhotoResponse,
    MyPhotosPrepareRequest,
    MyPhotosPrepareResponse,
)


class MyPhotosDeliveryService:
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
        self._settings = settings
        self._providers = providers
        context = MyPhotosDeliveryContext(
            session, settings, providers, require_passenger, ready_gallery, lock_passenger_identity
        )
        self._assets = MyPhotosDeliveryAssets(context)
        self._preparation = MyPhotosMediaPreparation(context, self._assets)
        self._authorizations = MyPhotosDeliveryAuthorizations(context, self._assets)
        self._plan = MyPhotosDownloadPlan(context)
        self._downloads = MyPhotosDownloadContent(context, self._assets)
        self._previews = MyPhotosPreviewContent(context, self._assets)

    async def prepare_media(
        self,
        *,
        claims: MobileAccessClaims,
        trip: AuthorizedMobileTrip,
        asset_id: uuid.UUID,
        request: MyPhotosPrepareRequest,
    ) -> MyPhotosPrepareResponse:
        return await self._preparation.prepare_media(
            claims=claims, trip=trip, asset_id=asset_id, request=request
        )

    async def authorize_downloads(
        self,
        *,
        claims: MobileAccessClaims,
        trip: AuthorizedMobileTrip,
        request: MyPhotosDownloadAuthorizationRequest,
    ) -> MyPhotosDownloadAuthorizationResponse:
        return await self._authorizations.authorize_downloads(
            claims=claims, trip=trip, request=request
        )

    async def download_plan(
        self,
        *,
        claims: MobileAccessClaims,
        trip: AuthorizedMobileTrip,
    ) -> MyPhotosDownloadPlanResponse:
        return await self._plan.download_plan(claims=claims, trip=trip)

    async def development_download_content(
        self,
        *,
        claims: MobileAccessClaims,
        trip: AuthorizedMobileTrip,
        authorization_id: uuid.UUID,
    ) -> tuple[bytes, str, str]:
        return await self._downloads.development_download_content(
            claims=claims, trip=trip, authorization_id=authorization_id
        )

    async def production_download_location(
        self,
        *,
        claims: MobileAccessClaims,
        trip: AuthorizedMobileTrip,
        authorization_id: uuid.UUID,
    ) -> DeliveryResolution:
        return await self._downloads.production_download_location(
            claims=claims, trip=trip, authorization_id=authorization_id
        )

    async def development_preview_content(
        self,
        *,
        claims: MobileAccessClaims,
        trip: AuthorizedMobileTrip,
        asset_id: uuid.UUID,
        variant: str,
    ) -> tuple[bytes, str]:
        return await self._previews.development_preview_content(
            claims=claims, trip=trip, asset_id=asset_id, variant=variant
        )

    async def production_preview_location(
        self,
        *,
        claims: MobileAccessClaims,
        trip: AuthorizedMobileTrip,
        asset_id: uuid.UUID,
        variant: Literal["thumbnail", "preview"],
    ) -> DeliveryResolution:
        return await self._previews.production_preview_location(
            claims=claims, trip=trip, asset_id=asset_id, variant=variant
        )

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
        return photo_response(
            settings=self._settings,
            providers=self._providers,
            gallery=gallery,
            group_id=group_id,
            account_cache_scope=account_cache_scope,
            match=match,
            asset=asset,
            thumbnail_variant=thumbnail_variant,
            preview_variant=preview_variant,
            optimized_variant=optimized_variant,
        )

    def _delivery_response_item(
        self,
        *,
        group_id: uuid.UUID,
        authorization: MyPhotoDeliveryAuthorizationModel,
        transport: str,
        retry_after_seconds: int | None,
    ) -> MyPhotosDownloadAuthorizationItemResponse:
        return _delivery_response_item(
            group_id=group_id,
            authorization=authorization,
            transport=transport,
            retry_after_seconds=retry_after_seconds,
        )

    @staticmethod
    def _clear_delivery_metadata(
        authorization: MyPhotoDeliveryAuthorizationModel,
    ) -> None:
        return _clear_delivery_metadata(authorization=authorization)

    async def _finalize_delivery_claims(
        self,
        results: list[tuple[uuid.UUID, str, DeliveryAuthorization | None, str | None]],
        *,
        access_ends_at: datetime | None = None,
    ) -> None:
        return await self._authorizations._finalize_delivery_claims(
            results=results, access_ends_at=access_ends_at
        )

    async def _current_delivery_asset(
        self,
        passenger_id: uuid.UUID,
        agency_id: uuid.UUID,
        group_id: uuid.UUID,
        asset_id: uuid.UUID,
    ) -> tuple[MyPhotoGalleryModel, MyPhotoMediaAssetModel]:
        return await self._assets._current_delivery_asset(
            passenger_id=passenger_id, agency_id=agency_id, group_id=group_id, asset_id=asset_id
        )

    async def _authorized_assets(
        self,
        passenger_identity_id: uuid.UUID,
        gallery: MyPhotoGalleryModel,
        asset_ids: list[uuid.UUID],
    ) -> dict[uuid.UUID, MyPhotoMediaAssetModel]:
        return await self._assets._authorized_assets(
            passenger_identity_id=passenger_identity_id, gallery=gallery, asset_ids=asset_ids
        )

    async def latest_optimized_variants(
        self,
        asset_ids: list[uuid.UUID],
        *,
        agency_id: uuid.UUID,
        group_id: uuid.UUID,
    ) -> dict[uuid.UUID, MyPhotoAssetVariantModel]:
        return await self._assets.latest_optimized_variants(
            asset_ids=asset_ids, agency_id=agency_id, group_id=group_id
        )

    async def latest_variants(
        self,
        asset_ids: list[uuid.UUID],
        *,
        agency_id: uuid.UUID,
        group_id: uuid.UUID,
        variant_kinds: tuple[str, ...],
    ) -> dict[tuple[uuid.UUID, str], MyPhotoAssetVariantModel]:
        return await self._assets.latest_variants(
            asset_ids=asset_ids, agency_id=agency_id, group_id=group_id, variant_kinds=variant_kinds
        )


__all__ = ["MyPhotosDeliveryService"]
