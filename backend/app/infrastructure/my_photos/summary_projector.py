"""Passenger-facing My Photos summary projection.

This read-only projection is isolated from enrollment mutations so the
application facade remains small while all counts retain one bounded-query
contract.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import cast

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.my_photos.states import (
    MEDIA_DELIVERY_READY_STATES,
    MEDIA_PREPARING_STATES,
    EnrollmentStatus,
)
from app.core.config.settings import Settings
from app.infrastructure.database.my_photos_models import (
    MyPhotoEnrollmentModel,
    MyPhotoGalleryModel,
    MyPhotoJobModel,
    MyPhotoMatchModel,
    MyPhotoMediaAssetModel,
    MyPhotoSearchRunModel,
)
from app.infrastructure.my_photos.providers import MyPhotosProviderBundle
from app.infrastructure.my_photos.telemetry import my_photos_metrics
from app.presentation.api.v1.schemas.my_photos_schemas import (
    MyPhotosCapabilityResponse,
    MyPhotosConsentResponse,
    MyPhotosEnrollmentResponse,
    MyPhotosGalleryResponse,
    MyPhotosResultsResponse,
    MyPhotosSearchRunResponse,
    MyPhotosSummaryResponse,
)


class MyPhotosSummaryProjector:
    """Build compact status/capability data without loading gallery rows."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        settings: Settings,
        providers: MyPhotosProviderBundle,
        gallery_window_state: Callable[[MyPhotoGalleryModel | None, datetime], str],
        search_response: Callable[[MyPhotoSearchRunModel | None], MyPhotosSearchRunResponse | None],
    ) -> None:
        self._session = session
        self._settings = settings
        self._providers = providers
        self._gallery_window_state = gallery_window_state
        self._search_response = search_response

    async def build(
        self,
        *,
        group_name: str,
        group_id: uuid.UUID,
        gallery: MyPhotoGalleryModel | None,
        enrollment: MyPhotoEnrollmentModel | None,
        search: MyPhotoSearchRunModel | None,
        passenger_identity_id: uuid.UUID,
    ) -> MyPhotosSummaryResponse:
        now = datetime.now(tz=UTC)
        gallery_is_enabled = bool(gallery is not None and gallery.feature_enabled)
        if not gallery_is_enabled:
            # A disabled gallery is an authoritative capability-off response,
            # not a passenger-data projection. Do not expose stale enrollment
            # or search state retained for a later re-enable.
            enrollment = None
            search = None
        provider_configured = self._providers.liveness.ready and self._providers.face_search.ready
        provider_transient = bool(
            provider_configured
            and search is not None
            and search.stable_error_code is not None
            and any(
                category in search.stable_error_code
                for category in ("UNAVAILABLE", "THROTTLED", "TIMEOUT")
            )
            and search.status in {"queued", "failed"}
        )
        provider_ready = provider_configured and not provider_transient
        window_state = self._gallery_window_state(gallery, now)
        feature_enabled = bool(
            gallery_is_enabled and window_state != "not_started"
        )
        gallery_status = (
            gallery.status if gallery is not None and gallery_is_enabled else "not_uploaded"
        )
        my_photos_metrics.gallery_state(gallery_status)
        consent_required = (
            enrollment is None
            or enrollment.status in {"revoked", "deleted"}
            or enrollment.consent_version != self._settings.my_photos.consent_version
        )
        # Expired galleries intentionally withhold every result count, but a
        # ready gallery must still publish its immutable snapshot revision so
        # the mobile response remains internally valid and can evict stale
        # cached rows against the correct revision.
        withheld_snapshot_revision = (
            gallery.published_revision
            if gallery is not None
            and gallery_is_enabled
            and gallery.status == "ready"
            and window_state == "expired"
            else 0
        )
        result_counts = MyPhotosResultsResponse(
            snapshot_revision=withheld_snapshot_revision,
            match_count=0,
            new_photo_count=0,
            downloadable_count=0,
            preparing_count=0,
            last_updated_at=None,
        )
        if gallery is not None and feature_enabled and window_state == "active":
            effective_result_revision = (
                await self._session.execute(
                    select(func.max(MyPhotoMatchModel.gallery_revision)).where(
                        MyPhotoMatchModel.passenger_identity_id == passenger_identity_id,
                        MyPhotoMatchModel.group_id == group_id,
                        MyPhotoMatchModel.gallery_revision <= gallery.published_revision,
                        MyPhotoMatchModel.active.is_(True),
                    )
                )
            ).scalar_one()
            prior_revision = (
                await self._session.execute(
                    select(func.max(MyPhotoSearchRunModel.gallery_revision)).where(
                        MyPhotoSearchRunModel.passenger_identity_id == passenger_identity_id,
                        MyPhotoSearchRunModel.group_id == group_id,
                        MyPhotoSearchRunModel.status == "complete",
                        MyPhotoSearchRunModel.gallery_revision < gallery.published_revision,
                    )
                )
            ).scalar_one()
            aggregate = (
                await self._session.execute(
                    select(
                        func.count(MyPhotoMatchModel.id),
                        func.coalesce(
                            func.sum(
                                case(
                                    (
                                        MyPhotoMediaAssetModel.availability_state.in_(
                                            tuple(MEDIA_DELIVERY_READY_STATES)
                                        ),
                                        1,
                                    ),
                                    else_=0,
                                )
                            ),
                            0,
                        ),
                        func.coalesce(
                            func.sum(
                                case(
                                    (
                                        MyPhotoMediaAssetModel.availability_state.in_(
                                            tuple(MEDIA_PREPARING_STATES)
                                        ),
                                        1,
                                    ),
                                    else_=0,
                                )
                            ),
                            0,
                        ),
                        func.max(MyPhotoMatchModel.updated_at),
                    )
                    .select_from(MyPhotoMatchModel)
                    .join(
                        MyPhotoMediaAssetModel,
                        MyPhotoMediaAssetModel.id == MyPhotoMatchModel.media_asset_id,
                    )
                    .where(
                        MyPhotoMatchModel.passenger_identity_id == passenger_identity_id,
                        MyPhotoMatchModel.group_id == group_id,
                        MyPhotoMatchModel.gallery_revision == effective_result_revision,
                        MyPhotoMatchModel.active.is_(True),
                        MyPhotoMediaAssetModel.availability_state != "removed",
                    )
                )
            ).one()
            new_photo_count = 0
            if (
                prior_revision is not None
                and effective_result_revision == gallery.published_revision
            ):
                prior_match = MyPhotoMatchModel.__table__.alias("prior_match")
                new_photo_count = int(
                    (
                        await self._session.execute(
                            select(func.count(MyPhotoMatchModel.id)).where(
                                MyPhotoMatchModel.passenger_identity_id == passenger_identity_id,
                                MyPhotoMatchModel.group_id == group_id,
                                MyPhotoMatchModel.gallery_revision == gallery.published_revision,
                                MyPhotoMatchModel.active.is_(True),
                                MyPhotoMatchModel.media_asset_id.in_(
                                    select(MyPhotoMediaAssetModel.id).where(
                                        MyPhotoMediaAssetModel.gallery_id == gallery.id,
                                        MyPhotoMediaAssetModel.availability_state != "removed",
                                    )
                                ),
                                ~select(prior_match.c.id)
                                .where(
                                    prior_match.c.passenger_identity_id == passenger_identity_id,
                                    prior_match.c.group_id == group_id,
                                    prior_match.c.gallery_revision == prior_revision,
                                    prior_match.c.media_asset_id
                                    == MyPhotoMatchModel.media_asset_id,
                                )
                                .exists(),
                            )
                        )
                    ).scalar_one()
                )
            result_counts = MyPhotosResultsResponse(
                snapshot_revision=(
                    int(effective_result_revision)
                    if effective_result_revision is not None
                    else int(search.gallery_revision)
                    if search is not None
                    and search.status == "complete"
                    and search.gallery_revision <= gallery.published_revision
                    else int(prior_revision or gallery.published_revision)
                ),
                match_count=int(aggregate[0] or 0),
                # First-ever results intentionally show zero "new" photos;
                # later revisions count current assets absent from the latest
                # prior completed gallery search, without loading asset IDs.
                new_photo_count=new_photo_count,
                downloadable_count=int(aggregate[1] or 0),
                preparing_count=int(aggregate[2] or 0),
                last_updated_at=aggregate[3],
            )
        stale_search = bool(
            feature_enabled
            and window_state == "active"
            and gallery is not None
            and enrollment is not None
            and enrollment.status == "enrolled"
            and (search is None or search.gallery_revision < gallery.published_revision)
        )
        refresh_failed = False
        if stale_search and gallery is not None:
            refresh_failed = bool(
                (
                    await self._session.execute(
                        select(func.count(MyPhotoJobModel.id)).where(
                            MyPhotoJobModel.gallery_id == gallery.id,
                            MyPhotoJobModel.job_type == "refresh_searches",
                            MyPhotoJobModel.target_revision == gallery.published_revision,
                            MyPhotoJobModel.status == "failed",
                        )
                    )
                ).scalar_one()
            )
        if gallery is None or not gallery.feature_enabled:
            experience_state = "feature_unavailable"
        elif window_state == "expired":
            experience_state = "access_expired"
        elif not feature_enabled:
            experience_state = "feature_unavailable"
        elif not provider_configured:
            experience_state = "provider_not_configured"
        elif provider_transient:
            experience_state = "provider_unavailable"
        elif gallery_status == "not_uploaded":
            experience_state = "gallery_not_uploaded"
        elif gallery_status in {"awaiting_upload", "processing"}:
            experience_state = "gallery_processing"
        elif gallery_status == "indexing":
            experience_state = "gallery_indexing"
        elif gallery_status in {"failed", "removed"}:
            experience_state = "nonrecoverable_error"
        elif enrollment is not None and enrollment.status == "deleted":
            experience_state = "enrollment_deleted"
        elif enrollment is not None and enrollment.status == "revoked":
            experience_state = "access_revoked"
        elif consent_required:
            experience_state = "consent_required"
        elif enrollment is None or enrollment.status == "ready":
            experience_state = "ready_to_scan"
        elif enrollment.status in {"session_pending", "processing"}:
            experience_state = "scan_running"
        elif enrollment.status == "rejected":
            experience_state = "liveness_rejected"
        elif enrollment.status == "cooldown":
            experience_state = "cooldown"
        elif enrollment.status == "revoked":
            experience_state = "access_revoked"
        elif stale_search:
            experience_state = "recoverable_error" if refresh_failed else "search_queued"
        elif search is not None and search.status == "queued":
            experience_state = "search_queued"
        elif search is not None and search.status == "searching":
            experience_state = "searching"
        elif search is not None and search.status == "failed":
            experience_state = "recoverable_error"
        elif search is not None and search.status == "cancelled":
            experience_state = "recoverable_error"
        elif search is not None and search.status == "complete" and result_counts.match_count == 0:
            experience_state = "no_matches"
        elif result_counts.preparing_count > 0:
            experience_state = "matches_preparing"
        elif result_counts.match_count > 0:
            experience_state = "matches_ready"
        else:
            experience_state = "ready_to_scan"
        gallery_updated_at = (
            gallery.updated_at if gallery is not None and gallery_is_enabled else now
        )
        enrollment_updated_at = enrollment.updated_at if enrollment is not None else now
        return MyPhotosSummaryResponse(
            group_id=group_id,
            group_name=group_name,
            experience_state=experience_state,  # type: ignore[arg-type]
            server_time=now,
            capability=MyPhotosCapabilityResponse(
                feature_enabled=feature_enabled,
                provider_ready=provider_ready,
                provider_state=(
                    "temporarily_unavailable"
                    if provider_transient
                    else "ready"
                    if provider_configured
                    else "not_configured"
                ),
                client_flow=self._providers.liveness.client_flow,
                supported_challenge_modes=(
                    ["movement_and_light", "movement_only"] if provider_configured else []
                ),
                retryable=provider_configured,
            ),
            gallery=MyPhotosGalleryResponse(
                status=gallery_status,  # type: ignore[arg-type]
                published_revision=(
                    gallery.published_revision
                    if gallery is not None and gallery_is_enabled
                    else 0
                ),
                media_version=(
                    gallery.media_version
                    if gallery is not None and gallery_is_enabled
                    else 0
                ),
                face_index_version=(
                    gallery.face_index_version
                    if gallery is not None and gallery_is_enabled
                    else 0
                ),
                total_asset_count=(
                    gallery.total_asset_count
                    if gallery is not None and gallery_is_enabled
                    else 0
                ),
                indexed_asset_count=(
                    gallery.indexed_asset_count
                    if gallery is not None and gallery_is_enabled
                    else 0
                ),
                failed_asset_count=(
                    gallery.failed_asset_count
                    if gallery is not None and gallery_is_enabled
                    else 0
                ),
                all_group_photos_enabled=(
                    gallery.all_group_photos_enabled
                    if gallery is not None and gallery_is_enabled
                    else False
                ),
                published_at=(
                    gallery.published_at
                    if gallery is not None and gallery_is_enabled
                    else None
                ),
                updated_at=gallery_updated_at,
            ),
            consent=MyPhotosConsentResponse(
                required=consent_required,
                required_version=self._settings.my_photos.consent_version,
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
            ),
            enrollment=MyPhotosEnrollmentResponse(
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
                    else self._settings.my_photos.maximum_liveness_attempts
                ),
                cooldown_until=enrollment.cooldown_until if enrollment is not None else None,
                enrolled_at=enrollment.enrolled_at if enrollment is not None else None,
                updated_at=enrollment_updated_at,
            ),
            # Search progress and match-tier counts are passenger result data.
            # Withhold the entire search projection outside the active access
            # window while retaining the gallery revision above so clients can
            # evict an expired cached snapshot deterministically.
            search=self._search_response(
                search
                if feature_enabled and window_state == "active" and not stale_search
                else None
            ),
            results=result_counts,
        )


__all__ = ["MyPhotosSummaryProjector"]
