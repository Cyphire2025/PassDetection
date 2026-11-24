"""Passenger summary orchestration with focused query, state and response owners."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import cast

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.my_photos.states import (
    ExperienceState,
)
from app.core.config.settings import Settings
from app.infrastructure.database.my_photos_models import (
    MyPhotoEnrollmentModel,
    MyPhotoGalleryModel,
    MyPhotoJobModel,
    MyPhotoSearchRunModel,
)
from app.infrastructure.my_photos.providers import MyPhotosProviderBundle
from app.infrastructure.my_photos.summary_counts import active_result_counts
from app.infrastructure.my_photos.summary_responses import (
    consent_response,
    enrollment_response,
    gallery_response,
)
from app.infrastructure.my_photos.summary_state import SummaryStateInputs
from app.infrastructure.my_photos.summary_state import experience_state as resolve_experience_state
from app.infrastructure.my_photos.telemetry import my_photos_metrics
from app.presentation.api.v1.schemas.my_photos_schemas import (
    MyPhotosCapabilityResponse,
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
        feature_enabled = bool(gallery_is_enabled and window_state != "not_started")
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
        if gallery is not None and feature_enabled and (window_state == "active"):
            result_counts = await active_result_counts(
                self._session,
                gallery=gallery,
                group_id=group_id,
                passenger_identity_id=passenger_identity_id,
                search=search,
            )
        stale_search = bool(
            feature_enabled
            and window_state == "active"
            and (gallery is not None)
            and (enrollment is not None)
            and (enrollment.status == "enrolled")
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
        experience_state = resolve_experience_state(
            SummaryStateInputs(
                gallery=gallery,
                window_state=window_state,
                feature_enabled=feature_enabled,
                provider_configured=provider_configured,
                provider_transient=provider_transient,
                gallery_status=gallery_status,
                enrollment=enrollment,
                consent_required=consent_required,
                stale_search=stale_search,
                refresh_failed=refresh_failed,
                search=search,
                result_counts=result_counts,
            )
        )
        return MyPhotosSummaryResponse(
            group_id=group_id,
            group_name=group_name,
            experience_state=cast("ExperienceState", experience_state),
            server_time=now,
            capability=MyPhotosCapabilityResponse(
                feature_enabled=feature_enabled,
                provider_ready=provider_ready,
                provider_state="temporarily_unavailable"
                if provider_transient
                else "ready"
                if provider_configured
                else "not_configured",
                client_flow=self._providers.liveness.client_flow,
                supported_challenge_modes=["movement_and_light", "movement_only"]
                if provider_configured
                else [],
                retryable=provider_configured,
            ),
            gallery=gallery_response(
                gallery,
                gallery_is_enabled=gallery_is_enabled,
                gallery_status=gallery_status,
                now=now,
            ),
            consent=consent_response(
                enrollment, consent_required=consent_required, settings=self._settings
            ),
            enrollment=enrollment_response(
                enrollment, consent_required=consent_required, settings=self._settings, now=now
            ),
            search=self._search_response(
                search
                if feature_enabled and window_state == "active" and (not stale_search)
                else None
            ),
            results=result_counts,
        )


__all__ = ["MyPhotosSummaryProjector"]
