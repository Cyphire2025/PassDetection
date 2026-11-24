"""Durable photo operation job policy."""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime

from app.application.my_photos.limits import MAX_MY_PHOTOS_MEDIA_BYTES
from app.application.my_photos.providers import (
    FaceIndexAsset,
    FaceIndexBatchResult,
    IndexedFaceOccurrence,
    MediaAvailabilityResult,
)
from app.application.my_photos.states import MEDIA_DELIVERY_READY_STATES
from app.core.config.settings import Settings
from app.infrastructure.database.my_photos_models import MyPhotoJobModel


def _validated_media_result(
    result: MediaAvailabilityResult, *, variant: str
) -> MediaAvailabilityResult:
    if result.delivery_version < 1:
        raise ValueError("Invalid media delivery version")
    if result.state not in MEDIA_DELIVERY_READY_STATES:
        if any(
            (
                value is not None
                for value in (
                    result.byte_size,
                    result.checksum_sha256,
                    result.storage_reference,
                    result.content_type,
                    result.width,
                    result.height,
                )
            )
        ):
            raise ValueError("Preparing media result carried delivery metadata")
        return result
    if (
        result.byte_size is None
        or not 1 <= result.byte_size <= MAX_MY_PHOTOS_MEDIA_BYTES
        or result.checksum_sha256 is None
        or (len(result.checksum_sha256) != 64)
        or any((character not in "0123456789abcdef" for character in result.checksum_sha256))
        or (result.storage_reference is None)
        or (not _valid_opaque(result.storage_reference, 4096))
        or (result.content_type not in {"image/jpeg", "image/png", "image/webp"})
        or (result.width is None)
        or (result.height is None)
        or (not 1 <= result.width <= 100000)
        or (not 1 <= result.height <= 100000)
    ):
        raise ValueError(f"Invalid {variant} media provider result")
    return result


def _validated_index_result(
    result: FaceIndexBatchResult, requested: tuple[FaceIndexAsset, ...]
) -> FaceIndexBatchResult:
    identities = {asset.asset_identity for asset in requested}
    if len(result.occurrences) > len(requested) * 100 or len(result.failures) > len(requested):
        raise ValueError("Unbounded index provider result")
    seen_references: set[str] = set()
    seen_idempotency: set[tuple[str, str]] = set()
    occurrence_assets: set[str] = set()
    for occurrence in result.occurrences:
        _validate_occurrence(occurrence, identities)
        occurrence_key = (occurrence.asset_identity, occurrence.idempotency_identity)
        if occurrence.provider_face_reference in seen_references:
            raise ValueError("Duplicate provider face reference")
        if occurrence_key in seen_idempotency:
            raise ValueError("Duplicate indexed face idempotency identity")
        seen_references.add(occurrence.provider_face_reference)
        seen_idempotency.add(occurrence_key)
        occurrence_assets.add(occurrence.asset_identity)
    failure_assets: set[str] = set()
    for failure in result.failures:
        if (
            failure.asset_identity not in identities
            or failure.asset_identity in failure_assets
            or failure.asset_identity in occurrence_assets
            or (not _valid_error(failure.stable_error_code))
        ):
            raise ValueError("Invalid index failure")
        failure_assets.add(failure.asset_identity)
    return result


def _validate_occurrence(occurrence: IndexedFaceOccurrence, identities: set[str]) -> None:
    box = occurrence.bounding_box
    if (
        occurrence.asset_identity not in identities
        or not _valid_opaque(occurrence.provider_face_reference, 512)
        or (not _valid_opaque(occurrence.idempotency_identity, 128))
        or (not _valid_opaque(occurrence.provider_model_version, 64))
        or (not 0 <= box.left <= 1)
        or (not 0 <= box.top <= 1)
        or (not 0 < box.width <= 1)
        or (not 0 < box.height <= 1)
        or (box.left + box.width > 1.000001)
        or (box.top + box.height > 1.000001)
        or (occurrence.quality_score is not None and (not 0 <= occurrence.quality_score <= 100))
    ):
        raise ValueError("Invalid indexed face occurrence")


def _retry_delay(job_id: uuid.UUID, attempt_count: int, settings: Settings) -> int:
    base = min(
        settings.my_photos.job_retry_max_seconds,
        settings.my_photos.job_retry_base_seconds * 2 ** min(max(attempt_count - 1, 0), 8),
    )
    digest = hashlib.sha256(f"{job_id}:{attempt_count}".encode()).digest()
    jitter = int.from_bytes(digest[:2], "big") % max(1, base // 2 + 1)
    return int(min(settings.my_photos.job_retry_max_seconds, base + jitter))


def _valid_opaque(value: str, maximum: int) -> bool:
    return bool(
        value
        and len(value) <= maximum
        and (value == value.strip())
        and value.isprintable()
        and ("://" not in value)
    )


def _valid_error(value: str) -> bool:
    return bool(
        value and len(value) <= 64 and (value == value.strip()) and value.replace("_", "").isalnum()
    )


def _index_publication_allowed(job: MyPhotoJobModel, settings: Settings) -> bool:
    if (
        job.total_count <= 0
        or job.processed_count != job.total_count
        or job.succeeded_count + job.failed_count != job.total_count
        or (job.succeeded_count <= 0)
    ):
        return False
    return bool(job.failed_count / job.total_count <= settings.my_photos.index_max_failure_ratio)


def _utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
