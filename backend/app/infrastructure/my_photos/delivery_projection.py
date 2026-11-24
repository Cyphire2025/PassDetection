"""Pure private photo metadata and delivery response projections."""

from __future__ import annotations

import hashlib
import uuid
from typing import Literal

from app.application.my_photos.states import (
    MEDIA_PREPARING_STATES,
)
from app.core.config.settings import Settings
from app.infrastructure.database.my_photos_models import (
    MyPhotoAssetVariantModel,
    MyPhotoDeliveryAuthorizationModel,
    MyPhotoGalleryModel,
    MyPhotoMatchModel,
    MyPhotoMediaAssetModel,
)
from app.infrastructure.my_photos.delivery_policy import (
    _SUPPORTED_DELIVERY_MIME,
    _optimized_variant_is_downloadable,
    _preview_variant_is_downloadable,
)
from app.infrastructure.my_photos.providers import MyPhotosProviderBundle
from app.infrastructure.my_photos.synthetic_media import synthetic_png
from app.presentation.api.v1.schemas.my_photos_schemas import (
    MyPhotosDownloadAuthorizationItemResponse,
    MyPhotosMediaDescriptor,
    MyPhotosPhotoResponse,
)


def photo_response(
    *,
    settings: Settings,
    providers: MyPhotosProviderBundle,
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
        settings.app_env == "development"
        and settings.my_photos.development_fixtures_enabled
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
    production_transport = providers.provider_name == "aws" and gallery.provider_name == "aws"
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
