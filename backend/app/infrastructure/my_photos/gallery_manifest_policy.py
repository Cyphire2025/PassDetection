"""Gallery manifest policy owner."""

from __future__ import annotations

import re
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import cast

from app.application.my_photos.errors import MyPhotosConflict
from app.application.my_photos.providers import MediaAvailabilityResult
from app.application.my_photos.states import MEDIA_DELIVERY_READY_STATES
from app.domain.entities.entities import User, UserRole
from app.domain.exceptions.exceptions import AuthorizationError, StepUpRequiredError
from app.infrastructure.database.my_photos_models import (
    MyPhotoGalleryManifestModel,
    MyPhotoGalleryModel,
    MyPhotoJobModel,
)
from app.infrastructure.my_photos.gallery_manifest_contracts import (
    GalleryManifestRequest,
    GalleryManifestResult,
    GalleryManifestVariant,
    ManifestDispatchState,
    ManifestState,
)

_ADMIN_MFA_MAX_AGE = timedelta(minutes=10)
_STABLE_ID = re.compile("^[A-Za-z0-9._:-]+$")


def _require_operator(actor: User, agency_id: uuid.UUID, mfa_verified_at: datetime) -> None:
    if (
        not actor.is_active
        or actor.credential_state != "active"
        or actor.role not in {UserRole.SUPER_ADMIN, UserRole.AGENCY_ADMIN}
        or (not actor.can_manage_agency(agency_id))
    ):
        raise AuthorizationError()
    now = datetime.now(tz=UTC)
    verified = _as_utc(mfa_verified_at)
    if not actor.mfa_enabled or verified > now or now - verified > _ADMIN_MFA_MAX_AGE:
        raise StepUpRequiredError()


def _require_gallery_scope(
    gallery: MyPhotoGalleryModel,
    *,
    request: GalleryManifestRequest,
    access_id: uuid.UUID,
    collection_reference: str,
) -> None:
    if (
        gallery.gc_group_access_id != access_id
        or gallery.agency_id != request.agency_id
        or gallery.group_id != request.group_id
    ):
        raise MyPhotosConflict(
            "MY_PHOTOS_GALLERY_SCOPE_CHANGED", "The gallery access scope changed."
        )
    if gallery.provider_name not in {None, "aws"} or (
        gallery.provider_collection_reference is not None
        and gallery.provider_collection_reference != collection_reference
    ):
        raise MyPhotosConflict(
            "MY_PHOTOS_GALLERY_PROVIDER_CONFLICT",
            "The gallery provider scope does not match this manifest.",
        )


def _require_manifest_header(
    manifest: MyPhotoGalleryManifestModel, request: GalleryManifestRequest, header_fingerprint: str
) -> None:
    if (
        manifest.header_fingerprint != header_fingerprint
        or manifest.target_revision != request.target_revision
        or manifest.total_asset_count != request.total_asset_count
        or (manifest.batch_count != request.batch_count)
    ):
        raise MyPhotosConflict(
            "MY_PHOTOS_MANIFEST_IDENTITY_CONFLICT",
            "The manifest identity was already used for different input.",
        )


def _require_variant_match(
    manifest: GalleryManifestVariant, provider: MediaAvailabilityResult
) -> None:
    if (
        provider.state not in MEDIA_DELIVERY_READY_STATES
        or provider.storage_reference is None
        or provider.source_object_reference != manifest.storage_reference
        or (provider.byte_size != manifest.byte_size)
        or (provider.checksum_sha256 != manifest.checksum_sha256)
        or (provider.delivery_version != manifest.delivery_version)
        or (provider.content_type != manifest.mime_type)
        or (provider.width != manifest.width)
        or (provider.height != manifest.height)
    ):
        raise ValueError("Variant media registration result is invalid")


def _result_with_job(
    manifest: MyPhotoGalleryManifestModel,
    job: MyPhotoJobModel,
    *,
    batch_replay: bool,
    manifest_replay: bool,
) -> GalleryManifestResult:
    state: ManifestState = cast(ManifestState, job.status)
    return GalleryManifestResult(
        manifest_id=manifest.id,
        gallery_id=manifest.gallery_id,
        index_job_id=job.id,
        target_revision=manifest.target_revision,
        received_asset_count=manifest.received_asset_count,
        total_asset_count=manifest.total_asset_count,
        batch_count=manifest.batch_count,
        state=state,
        batch_replay=batch_replay,
        manifest_replay=manifest_replay,
        content_fingerprint=manifest.content_fingerprint,
        dispatch_state="not_required",
    )


def _dispatch_result(
    result: GalleryManifestResult, *, dispatch: Callable[[uuid.UUID], None]
) -> GalleryManifestResult:
    if result.index_job_id is None:
        return result
    try:
        dispatch(result.index_job_id)
        state: ManifestDispatchState = "dispatched"
    except Exception:
        state = "deferred"
    return GalleryManifestResult(
        manifest_id=result.manifest_id,
        gallery_id=result.gallery_id,
        index_job_id=result.index_job_id,
        target_revision=result.target_revision,
        received_asset_count=result.received_asset_count,
        total_asset_count=result.total_asset_count,
        batch_count=result.batch_count,
        state=result.state,
        batch_replay=result.batch_replay,
        manifest_replay=result.manifest_replay,
        content_fingerprint=result.content_fingerprint,
        dispatch_state=state,
    )


def _valid_stable(value: str, *, maximum: int) -> bool:
    return 1 <= len(value) <= maximum and _STABLE_ID.fullmatch(value) is not None


def _as_utc(value: datetime) -> datetime:
    return value.astimezone(UTC) if value.utcoffset() is not None else value.replace(tzinfo=UTC)
