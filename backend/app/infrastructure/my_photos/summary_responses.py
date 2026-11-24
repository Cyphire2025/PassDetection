"""Existing public gallery, consent and enrollment response formatting."""

from __future__ import annotations

from datetime import datetime
from typing import cast

from app.application.my_photos.states import EnrollmentStatus, GalleryStatus
from app.core.config.settings import Settings
from app.infrastructure.database.my_photos_models import MyPhotoEnrollmentModel, MyPhotoGalleryModel
from app.presentation.api.v1.schemas.my_photos_schemas import (
    MyPhotosConsentResponse,
    MyPhotosEnrollmentResponse,
    MyPhotosGalleryResponse,
)


def gallery_response(
    gallery: MyPhotoGalleryModel | None,
    *,
    gallery_is_enabled: bool,
    gallery_status: str,
    now: datetime,
) -> MyPhotosGalleryResponse:
    """Project the existing gallery response without querying."""
    gallery_updated_at = gallery.updated_at if gallery is not None and gallery_is_enabled else now
    return MyPhotosGalleryResponse(
        status=cast("GalleryStatus", gallery_status),
        published_revision=(
            gallery.published_revision if gallery is not None and gallery_is_enabled else 0
        ),
        media_version=(gallery.media_version if gallery is not None and gallery_is_enabled else 0),
        face_index_version=(
            gallery.face_index_version if gallery is not None and gallery_is_enabled else 0
        ),
        total_asset_count=(
            gallery.total_asset_count if gallery is not None and gallery_is_enabled else 0
        ),
        indexed_asset_count=(
            gallery.indexed_asset_count if gallery is not None and gallery_is_enabled else 0
        ),
        failed_asset_count=(
            gallery.failed_asset_count if gallery is not None and gallery_is_enabled else 0
        ),
        all_group_photos_enabled=(
            gallery.all_group_photos_enabled
            if gallery is not None and gallery_is_enabled
            else False
        ),
        published_at=(gallery.published_at if gallery is not None and gallery_is_enabled else None),
        updated_at=gallery_updated_at,
    )


def consent_response(
    enrollment: MyPhotoEnrollmentModel | None, *, consent_required: bool, settings: Settings
) -> MyPhotosConsentResponse:
    """Project the existing consent response without querying."""
    return MyPhotosConsentResponse(
        required=consent_required,
        required_version=settings.my_photos.consent_version,
        accepted_version=enrollment.consent_version if enrollment is not None else None,
        accepted_at=enrollment.consented_at if enrollment is not None else None,
        purpose="Find event photos in which you appear for this selected trip only.",
        biometric_data_used=(
            "A server-verified live reference face is used only to search this trip's "
            "pre-indexed gallery. Passport and profile photos are not reused. It is not "
            "used for advertising, model training, or unrelated identification."
        ),
        retention=(
            "The reference is retained only under the selected trip's reviewed retention "
            "policy and can be deleted or revoked."
        ),
        provider_processing=(
            "An approved face-processing provider processes the Face Scan. Provider audit "
            "image retention is disabled by default."
        ),
        deletion=(
            "Delete Face Scan removes the enrollment reference. Downloaded event photos "
            "are separate and are not silently deleted."
        ),
    )


def enrollment_response(
    enrollment: MyPhotoEnrollmentModel | None,
    *,
    consent_required: bool,
    settings: Settings,
    now: datetime,
) -> MyPhotosEnrollmentResponse:
    """Project the existing enrollment response without querying."""
    enrollment_updated_at = enrollment.updated_at if enrollment is not None else now
    return MyPhotosEnrollmentResponse(
        status=cast(
            "EnrollmentStatus",
            enrollment.status
            if enrollment is not None and enrollment.status in {"deleted", "revoked"}
            else "consent_required"
            if consent_required
            else enrollment.status
            if enrollment is not None
            else "consent_required",
        ),
        reference_version=(
            enrollment.reference_version
            if enrollment is not None and enrollment.reference_version >= 1
            else None
        ),
        attempts_remaining=(
            max(enrollment.max_attempts - enrollment.attempt_count, 0)
            if enrollment is not None
            else settings.my_photos.maximum_liveness_attempts
        ),
        cooldown_until=enrollment.cooldown_until if enrollment is not None else None,
        enrolled_at=enrollment.enrolled_at if enrollment is not None else None,
        updated_at=enrollment_updated_at,
    )
