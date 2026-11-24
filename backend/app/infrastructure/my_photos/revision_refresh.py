"""Bounded current-lease passenger search fanout with parent-before-child writes."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select

from app.core.config.settings import Settings
from app.infrastructure.database.my_photos_models import (
    MyPhotoEnrollmentModel,
    MyPhotoFaceOccurrenceModel,
    MyPhotoJobModel,
    MyPhotoSearchRunModel,
)
from app.infrastructure.my_photos.operational_claim_queries import locked_claim_candidate
from app.infrastructure.my_photos.revision_contracts import (
    RefreshFanoutResult,
    RefreshFanoutState,
    RevisionContext,
)
from app.infrastructure.my_photos.revision_policy import (
    _checkpoint_uuid,
    _complete_job,
    _fail_job,
    _refresh_claim_current,
)


async def execute_refresh_fanout(
    ctx: RevisionContext,
    *,
    job_id: uuid.UUID,
    lease_owner: str,
    settings: Settings,
) -> RefreshFanoutResult:
    """Create current-revision search jobs without materializing all passengers."""

    async with ctx.sessions() as session:
        candidate = await locked_claim_candidate(session, job_id)
        if candidate is None:
            return RefreshFanoutResult("lease_lost")
        job, gallery = candidate
        if not _refresh_claim_current(job, lease_owner, datetime.now(tz=UTC)):
            return RefreshFanoutResult("lease_lost")
        if (
            not gallery.feature_enabled
            or gallery.status != "ready"
            or gallery.published_revision != job.target_revision
            or gallery.published_at is None
        ):
            _fail_job(job, "REFRESH_GALLERY_STALE")
            await session.commit()
            return RefreshFanoutResult("failed")

        checkpoint = _checkpoint_uuid(job.checkpoint_cursor)
        enrollment_query = select(MyPhotoEnrollmentModel).where(
            MyPhotoEnrollmentModel.agency_id == gallery.agency_id,
            MyPhotoEnrollmentModel.group_id == gallery.group_id,
            MyPhotoEnrollmentModel.status == "enrolled",
            MyPhotoEnrollmentModel.provider_reference_handle.is_not(None),
            MyPhotoEnrollmentModel.consent_version == settings.my_photos.consent_version,
            MyPhotoEnrollmentModel.enrolled_at.is_not(None),
            MyPhotoEnrollmentModel.enrolled_at <= gallery.published_at,
        )
        if checkpoint is not None:
            enrollment_query = enrollment_query.where(MyPhotoEnrollmentModel.id > checkpoint)
        enrollments = list(
            (
                await session.execute(
                    enrollment_query.order_by(MyPhotoEnrollmentModel.id).limit(
                        settings.my_photos.job_batch_size
                    )
                )
            ).scalars()
        )
        if not _refresh_claim_current(job, lease_owner, datetime.now(tz=UTC)):
            return RefreshFanoutResult("lease_lost")
        if not enrollments:
            _complete_job(job)
            await session.commit()
            return RefreshFanoutResult("succeeded")

        total_faces = int(
            (
                await session.execute(
                    select(func.count(MyPhotoFaceOccurrenceModel.id)).where(
                        MyPhotoFaceOccurrenceModel.agency_id == gallery.agency_id,
                        MyPhotoFaceOccurrenceModel.group_id == gallery.group_id,
                        MyPhotoFaceOccurrenceModel.index_version <= gallery.face_index_version,
                        MyPhotoFaceOccurrenceModel.active.is_(True),
                    )
                )
            ).scalar_one()
        )
        passenger_ids = tuple(row.passenger_identity_id for row in enrollments)
        existing = set(
            (
                await session.execute(
                    select(
                        MyPhotoSearchRunModel.passenger_identity_id,
                        MyPhotoSearchRunModel.enrollment_version,
                    ).where(
                        MyPhotoSearchRunModel.gallery_id == gallery.id,
                        MyPhotoSearchRunModel.gallery_revision == gallery.published_revision,
                        MyPhotoSearchRunModel.passenger_identity_id.in_(passenger_ids),
                    )
                )
            ).tuples()
        )

        if not _refresh_claim_current(job, lease_owner, datetime.now(tz=UTC)):
            return RefreshFanoutResult("lease_lost")
        search_rows: list[MyPhotoSearchRunModel] = []
        job_rows: list[MyPhotoJobModel] = []
        created_ids: list[uuid.UUID] = []
        for enrollment in enrollments:
            identity = (enrollment.passenger_identity_id, enrollment.reference_version)
            if identity in existing:
                continue
            search_id = uuid.uuid4()
            correlation_id = uuid.uuid4().hex
            idempotency_key = (
                f"refresh:r{gallery.published_revision}:e{enrollment.id.hex}:"
                f"v{enrollment.reference_version}"
            )
            search_rows.append(
                MyPhotoSearchRunModel(
                    id=search_id,
                    enrollment_id=enrollment.id,
                    passenger_identity_id=enrollment.passenger_identity_id,
                    gallery_id=gallery.id,
                    agency_id=gallery.agency_id,
                    group_id=gallery.group_id,
                    gallery_revision=gallery.published_revision,
                    face_index_version=gallery.face_index_version,
                    enrollment_version=enrollment.reference_version,
                    idempotency_key=idempotency_key,
                    status="queued",
                    total_face_count=total_faces,
                    max_attempts=settings.my_photos.job_max_attempts,
                    correlation_id=correlation_id,
                )
            )
            job_rows.append(
                MyPhotoJobModel(
                    gallery_id=gallery.id,
                    search_run_id=search_id,
                    agency_id=gallery.agency_id,
                    group_id=gallery.group_id,
                    job_type="search_passenger",
                    status="queued",
                    idempotency_key=idempotency_key,
                    max_attempts=settings.my_photos.job_max_attempts,
                    total_count=total_faces,
                    correlation_id=correlation_id,
                )
            )
            created_ids.append(search_id)

        if search_rows:
            # No ORM relationship links these mappers. Flush parent searches
            # once per bounded batch before queuing child jobs with immediate FKs.
            session.add_all(search_rows)
            await session.flush()
            if not _refresh_claim_current(job, lease_owner, datetime.now(tz=UTC)):
                return RefreshFanoutResult("lease_lost")
            session.add_all(job_rows)
        handled = len(enrollments)
        job.processed_count = min(job.total_count, job.processed_count + handled)
        job.succeeded_count = job.processed_count
        job.checkpoint_cursor = str(enrollments[-1].id)
        job.heartbeat_at = datetime.now(tz=UTC)
        if handled < settings.my_photos.job_batch_size or job.processed_count >= job.total_count:
            _complete_job(job)
            state: RefreshFanoutState = "succeeded"
        else:
            job.status = "retrying"
            job.attempt_count = 0
            job.lease_owner = None
            job.lease_expires_at = None
            job.next_attempt_at = None
            state = "continuing"
        await session.commit()
        return RefreshFanoutResult(state, tuple(created_ids))
