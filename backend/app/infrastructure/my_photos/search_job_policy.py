"""Bounded passenger-search provider validation, windows and retry categories."""

from __future__ import annotations

import hashlib
import math
from datetime import UTC, datetime

from app.application.my_photos.providers import FaceSearchResult, ProviderFaceMatch
from app.core.config.settings import Settings
from app.infrastructure.database.my_photos_models import MyPhotoGalleryModel
from app.infrastructure.my_photos.search_job_contracts import _SearchClaim


def _validated_provider_result(
    result: FaceSearchResult,
    *,
    maximum_results: int,
) -> FaceSearchResult:
    model_version = result.provider_model_version
    if (
        not isinstance(model_version, str)
        or not 1 <= len(model_version) <= 64
        or model_version != model_version.strip()
        or any(ord(character) < 32 for character in model_version)
    ):
        raise ValueError("provider model version is invalid")
    if not isinstance(result.matches, tuple) or len(result.matches) > maximum_results:
        raise ValueError("provider result count is invalid")

    # Provider redelivery may repeat a face reference. Coalesce it
    # deterministically to the highest bounded similarity instead of allowing
    # duplicate application match rows or last-write-wins behavior.
    unique: dict[str, float] = {}
    for match in result.matches:
        reference = match.provider_face_reference
        similarity = match.similarity
        if (
            not isinstance(reference, str)
            or not 1 <= len(reference) <= 512
            or reference != reference.strip()
            or any(ord(character) < 32 for character in reference)
            or isinstance(similarity, bool)
            or not isinstance(similarity, (int, float))
            or not math.isfinite(float(similarity))
            or not 0.0 <= float(similarity) <= 100.0
        ):
            raise ValueError("provider face match is invalid")
        unique[reference] = max(unique.get(reference, 0.0), float(similarity))

    normalized = tuple(
        ProviderFaceMatch(provider_face_reference=reference, similarity=similarity)
        for reference, similarity in sorted(unique.items())
    )
    return FaceSearchResult(
        matches=normalized,
        provider_model_version=model_version,
    )


def _retry_delay(claim: _SearchClaim, settings: Settings) -> int:
    base = min(
        settings.my_photos.job_retry_max_seconds,
        settings.my_photos.job_retry_base_seconds * (2 ** min(claim.attempt_count - 1, 8)),
    )
    digest = hashlib.sha256(f"{claim.search_run_id}:{claim.attempt_count}".encode("ascii")).digest()
    jitter = int.from_bytes(digest[:2], "big") % max(1, base // 2 + 1)
    return int(min(settings.my_photos.job_retry_max_seconds, base + jitter))


def _stable_error_code(value: str) -> str:
    normalized = "".join(
        char if char.isascii() and (char.isalnum() or char == "_") else "_"
        for char in value.upper()
    ).strip("_")
    return (normalized or "SEARCH_FAILED")[:64]


def _gallery_window_closed(gallery: MyPhotoGalleryModel, now: datetime) -> bool:
    return bool(
        (gallery.availability_starts_at is not None and now < _utc(gallery.availability_starts_at))
        or (gallery.availability_ends_at is not None and now >= _utc(gallery.availability_ends_at))
    )


def _utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
