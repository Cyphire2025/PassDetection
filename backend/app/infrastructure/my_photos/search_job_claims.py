"""Passenger-serialized search admission and pre-provider lease claims."""

from __future__ import annotations

import math
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.core.config.settings import Settings
from app.infrastructure.database.gc_mobile_models import MobilePassengerIdentityModel
from app.infrastructure.database.my_photos_models import (
    MyPhotoEnrollmentModel,
    MyPhotoGalleryModel,
    MyPhotoJobModel,
    MyPhotoSearchRunModel,
)
from app.infrastructure.my_photos.search_job_contracts import (
    SearchJobExecutionResult,
    SearchWorkerContext,
    _SearchClaim,
)
from app.infrastructure.my_photos.search_job_lifecycle import _audit_search, _mark_terminal_failure
from app.infrastructure.my_photos.search_job_policy import _gallery_window_closed, _utc
from app.infrastructure.my_photos.telemetry import my_photos_metrics


async def _claim_search(
    ctx: SearchWorkerContext,
    search_run_id: uuid.UUID,
    lease_owner: str,
    settings: Settings,
) -> _SearchClaim | SearchJobExecutionResult:
    async with ctx.session_factory() as session:
        scope = (
            await session.execute(
                select(
                    MyPhotoSearchRunModel.passenger_identity_id,
                    MyPhotoSearchRunModel.agency_id,
                    MyPhotoSearchRunModel.group_id,
                ).where(MyPhotoSearchRunModel.id == search_run_id)
            )
        ).one_or_none()
        if scope is None:
            return SearchJobExecutionResult(state="noop")
        await session.execute(
            select(MobilePassengerIdentityModel.id)
            .where(
                MobilePassengerIdentityModel.id == scope.passenger_identity_id,
                MobilePassengerIdentityModel.agency_id == scope.agency_id,
                MobilePassengerIdentityModel.group_id == scope.group_id,
            )
            .with_for_update()
        )
        search = (
            await session.execute(
                select(MyPhotoSearchRunModel)
                .where(MyPhotoSearchRunModel.id == search_run_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if search is None or search.status in {"complete", "cancelled", "failed"}:
            return SearchJobExecutionResult(state="noop")
        job = (
            await session.execute(
                select(MyPhotoJobModel)
                .where(
                    MyPhotoJobModel.search_run_id == search.id,
                    MyPhotoJobModel.job_type == "search_passenger",
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if job is None:
            search.status = "failed"
            search.stable_error_code = "SEARCH_JOB_MISSING"
            search.completed_at = datetime.now(tz=UTC)
            await _audit_search(session, search, "failed", settings)
            await session.commit()
            my_photos_metrics.job("failed")
            return SearchJobExecutionResult(state="failed")

        now = datetime.now(tz=UTC)
        if job.cancellation_requested_at is not None:
            search.status = "cancelled"
            search.completed_at = now
            search.lease_owner = None
            search.lease_expires_at = None
            job.status = "cancelled"
            job.completed_at = now
            job.lease_owner = None
            job.lease_expires_at = None
            await session.commit()
            my_photos_metrics.job("cancelled")
            return SearchJobExecutionResult(state="cancelled")
        if job.next_attempt_at is not None and _utc(job.next_attempt_at) > now:
            retry_after = max(1, int((_utc(job.next_attempt_at) - now).total_seconds()))
            return SearchJobExecutionResult("retrying", retry_after)
        if (
            search.lease_owner is not None
            and search.lease_expires_at is not None
            and _utc(search.lease_expires_at) > now
        ):
            my_photos_metrics.job("lease_busy")
            retry_after = max(
                1,
                math.ceil((_utc(search.lease_expires_at) - now).total_seconds()),
            )
            return SearchJobExecutionResult(state="lease_busy", retry_after_seconds=retry_after)
        if search.attempt_count >= search.max_attempts or job.attempt_count >= job.max_attempts:
            _mark_terminal_failure(search, job, now, "SEARCH_RETRY_EXHAUSTED")
            await _audit_search(session, search, "failed", settings)
            await session.commit()
            my_photos_metrics.job("failed")
            return SearchJobExecutionResult(state="failed")

        enrollment = (
            await session.execute(
                select(MyPhotoEnrollmentModel).where(
                    MyPhotoEnrollmentModel.id == search.enrollment_id,
                    MyPhotoEnrollmentModel.passenger_identity_id == search.passenger_identity_id,
                    MyPhotoEnrollmentModel.agency_id == search.agency_id,
                    MyPhotoEnrollmentModel.group_id == search.group_id,
                    MyPhotoEnrollmentModel.reference_version == search.enrollment_version,
                    MyPhotoEnrollmentModel.status == "enrolled",
                )
            )
        ).scalar_one_or_none()
        gallery = (
            await session.execute(
                select(MyPhotoGalleryModel).where(
                    MyPhotoGalleryModel.id == search.gallery_id,
                    MyPhotoGalleryModel.agency_id == search.agency_id,
                    MyPhotoGalleryModel.group_id == search.group_id,
                    MyPhotoGalleryModel.feature_enabled.is_(True),
                    MyPhotoGalleryModel.status == "ready",
                    MyPhotoGalleryModel.published_revision == search.gallery_revision,
                    MyPhotoGalleryModel.face_index_version == search.face_index_version,
                )
            )
        ).scalar_one_or_none()
        if (
            enrollment is None
            or gallery is None
            or enrollment.provider_reference_handle is None
            or gallery.provider_collection_reference is None
            or _gallery_window_closed(gallery, now)
        ):
            _mark_terminal_failure(search, job, now, "SEARCH_SCOPE_STALE")
            await _audit_search(session, search, "failed", settings)
            await session.commit()
            my_photos_metrics.job("failed")
            return SearchJobExecutionResult(state="failed")

        redelivery = search.attempt_count > 0 or job.attempt_count > 0
        if redelivery:
            my_photos_metrics.idempotent_redelivery("search")
        lease_expires_at = now + timedelta(seconds=settings.my_photos.job_lease_seconds)
        search.status = "searching"
        search.started_at = search.started_at or now
        search.attempt_count += 1
        search.lease_owner = lease_owner
        search.lease_expires_at = lease_expires_at
        search.heartbeat_at = now
        search.stable_error_code = None
        job.status = "running"
        job.attempt_count += 1
        job.started_at = job.started_at or now
        job.lease_owner = lease_owner
        job.lease_expires_at = lease_expires_at
        job.heartbeat_at = now
        job.next_attempt_at = None
        job.stable_error_code = None
        job.error_detail = None
        await session.commit()
        my_photos_metrics.job("redelivered" if redelivery else "claimed")
        return _SearchClaim(
            search_run_id=search.id,
            job_id=job.id,
            lease_owner=lease_owner,
            agency_id=search.agency_id,
            group_id=search.group_id,
            passenger_identity_id=search.passenger_identity_id,
            enrollment_id=search.enrollment_id,
            gallery_id=search.gallery_id,
            gallery_revision=search.gallery_revision,
            face_index_version=search.face_index_version,
            enrollment_version=search.enrollment_version,
            collection_reference=gallery.provider_collection_reference,
            reference_face_handle=enrollment.provider_reference_handle,
            total_face_count=search.total_face_count,
            attempt_count=search.attempt_count,
            max_attempts=min(search.max_attempts, job.max_attempts),
        )
