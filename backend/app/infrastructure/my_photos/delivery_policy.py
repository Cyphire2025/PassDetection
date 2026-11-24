"""Private photo delivery policy rules."""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime
from typing import Literal

from app.application.my_photos.states import (
    MEDIA_DELIVERY_READY_STATES,
)
from app.infrastructure.database.my_photos_models import (
    MyPhotoAssetVariantModel,
    MyPhotoGalleryModel,
    MyPhotoMediaAssetModel,
)
from app.presentation.api.v1.schemas.my_photos_schemas import (
    MyPhotosDownloadAuthorizationRequest,
)

_SUPPORTED_DELIVERY_MIME = frozenset({"image/jpeg", "image/png", "image/webp"})


def _delivery_deadline(
    expiry: datetime, gallery: MyPhotoGalleryModel, *, content_expires_at: datetime | None = None
) -> datetime:
    deadline = _as_utc(expiry)
    if gallery.availability_ends_at is not None:
        deadline = min(deadline, _as_utc(gallery.availability_ends_at))
    if content_expires_at is not None:
        deadline = min(deadline, _as_utc(content_expires_at))
    return deadline


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
