"""Atomic gallery publication and bounded passenger-search refresh fan-out."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.settings import Settings
from app.infrastructure.database.my_photos_models import (
    MyPhotoEnrollmentModel,
    MyPhotoFaceOccurrenceModel,
    MyPhotoGalleryManifestModel,
    MyPhotoGalleryModel,
    MyPhotoJobModel,
    MyPhotoMediaAssetModel,
    MyPhotoSearchRunModel,
)
from app.infrastructure.database.session import AsyncSessionFactory

RefreshFanoutState = Literal["succeeded", "continuing", "failed", "lease_lost"]


@dataclass(frozen=True, slots=True)
class RefreshFanoutResult:
    state: RefreshFanoutState
    search_run_ids: tuple[uuid.UUID, ...] = ()


async def publish_gallery_revision(
    session: AsyncSession,
    *,
    gallery: MyPhotoGalleryModel,
    index_job: MyPhotoJobModel,
    settings: Settings,
    published_at: datetime,
) -> uuid.UUID | None:
    """Publish exactly the indexed target and durably schedule bounded refresh fan-out."""

    target_revision = index_job.target_revision
    if target_revision is None or target_revision != gallery.published_revision + 1:
        raise ValueError("Gallery publication target is stale")

    manifest: MyPhotoGalleryManifestModel | None = None
    if getattr(index_job, "request_fingerprint", None) is not None:
        manifest = (
            await session.execute(
                select(MyPhotoGalleryManifestModel)
                .where(
                    MyPhotoGalleryManifestModel.gallery_id == gallery.id,
                    MyPhotoGalleryManifestModel.agency_id == gallery.agency_id,
                    MyPhotoGalleryManifestModel.group_id == gallery.group_id,
                    MyPhotoGalleryManifestModel.manifest_identity == index_job.idempotency_key,
                    MyPhotoGalleryManifestModel.target_revision == target_revision,
                    MyPhotoGalleryManifestModel.content_fingerprint
                    == index_job.request_fingerprint,
                    MyPhotoGalleryManifestModel.status == "indexing",
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if manifest is None or manifest.total_asset_count != index_job.total_count:
            raise ValueError("Gallery publication manifest is invalid")

    coverage = (
        await session.execute(
            select(
                func.count(MyPhotoMediaAssetModel.id),
                func.count(MyPhotoMediaAssetModel.id).filter(
                    MyPhotoMediaAssetModel.processing_state == "indexed"
                ),
                func.count(MyPhotoMediaAssetModel.id).filter(
                    MyPhotoMediaAssetModel.processing_state == "failed"
                ),
            ).where(
                MyPhotoMediaAssetModel.gallery_id == gallery.id,
                MyPhotoMediaAssetModel.published_revision == target_revision,
                MyPhotoMediaAssetModel.processing_state != "removed",
            )
        )
    ).one()
    if (
        int(coverage[0]) != index_job.total_count
        or int(coverage[1]) != index_job.succeeded_count
        or int(coverage[2]) != index_job.failed_count
        or int(coverage[1]) + int(coverage[2]) != int(coverage[0])
    ):
        raise ValueError("Gallery publication coverage is incomplete")

    if manifest is not None:
        gallery.media_version = target_revision
        gallery.face_index_version = target_revision
        gallery.all_group_photos_enabled = manifest.all_group_photos_enabled
        gallery.provider_collection_reference = manifest.provider_collection_reference
        gallery.provider_name = "aws"
        gallery.index_model_version = manifest.provider_model_version
        gallery.match_config_version = manifest.match_config_version
        gallery.retention_policy_version = manifest.retention_policy_version
        gallery.retention_days = manifest.retention_days
        gallery.availability_starts_at = manifest.availability_starts_at
        gallery.availability_ends_at = manifest.availability_ends_at
        manifest.status = "finalized"
    gallery.published_revision = target_revision
    gallery.status = "ready"
    gallery.published_at = published_at
    gallery.total_asset_count = int(
        (
            await session.execute(
                select(func.count(MyPhotoMediaAssetModel.id)).where(
                    MyPhotoMediaAssetModel.gallery_id == gallery.id,
                    MyPhotoMediaAssetModel.published_revision <= target_revision,
                    MyPhotoMediaAssetModel.processing_state != "removed",
                )
            )
        ).scalar_one()
    )

    eligible_count = int(
        (
            await session.execute(
                select(func.count(MyPhotoEnrollmentModel.id)).where(
                    MyPhotoEnrollmentModel.agency_id == gallery.agency_id,
                    MyPhotoEnrollmentModel.group_id == gallery.group_id,
                    MyPhotoEnrollmentModel.status == "enrolled",
                    MyPhotoEnrollmentModel.provider_reference_handle.is_not(None),
                    MyPhotoEnrollmentModel.consent_version == settings.my_photos.consent_version,
                    MyPhotoEnrollmentModel.enrolled_at.is_not(None),
                    MyPhotoEnrollmentModel.enrolled_at <= published_at,
                )
            )
        ).scalar_one()
    )
    if eligible_count == 0:
        return None

    refresh_job = MyPhotoJobModel(
        gallery_id=gallery.id,
        agency_id=gallery.agency_id,
        group_id=gallery.group_id,
        job_type="refresh_searches",
        status="queued",
        idempotency_key=f"gallery-revision:{target_revision}",
        target_revision=target_revision,
        max_attempts=settings.my_photos.job_max_attempts,
        total_count=eligible_count,
        correlation_id=uuid.uuid4().hex,
    )
    session.add(refresh_job)
    await session.flush()
    return refresh_job.id


async def execute_refresh_fanout(
    *,
    job_id: uuid.UUID,
    lease_owner: str,
    settings: Settings,
) -> RefreshFanoutResult:
    """Create current-revision search jobs without materializing all passengers."""

    async with AsyncSessionFactory() as session:
        job = (
            await session.execute(
                select(MyPhotoJobModel)
                .where(
                    MyPhotoJobModel.id == job_id,
                    MyPhotoJobModel.job_type == "refresh_searches",
                    MyPhotoJobModel.status == "running",
                    MyPhotoJobModel.lease_owner == lease_owner,
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if job is None:
            return RefreshFanoutResult("lease_lost")
        gallery = (
            await session.execute(
                select(MyPhotoGalleryModel)
                .where(
                    MyPhotoGalleryModel.id == job.gallery_id,
                    MyPhotoGalleryModel.agency_id == job.agency_id,
                    MyPhotoGalleryModel.group_id == job.group_id,
                    MyPhotoGalleryModel.feature_enabled.is_(True),
                    MyPhotoGalleryModel.status == "ready",
                    MyPhotoGalleryModel.published_revision == job.target_revision,
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if gallery is None or gallery.published_at is None:
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
            session.add(
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
            session.add(
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


def _checkpoint_uuid(value: str | None) -> uuid.UUID | None:
    if value is None:
        return None
    try:
        return uuid.UUID(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Invalid refresh checkpoint") from exc


def _complete_job(job: MyPhotoJobModel) -> None:
    now = datetime.now(tz=UTC)
    job.status = "succeeded"
    job.attempt_count = 0
    job.processed_count = job.total_count
    job.succeeded_count = job.total_count
    job.failed_count = 0
    job.completed_at = now
    job.heartbeat_at = now
    job.lease_owner = None
    job.lease_expires_at = None
    job.next_attempt_at = None
    job.stable_error_code = None


def _fail_job(job: MyPhotoJobModel, error_code: str) -> None:
    now = datetime.now(tz=UTC)
    job.status = "failed"
    job.stable_error_code = error_code
    job.error_detail = "Gallery refresh fan-out stopped with a stable category."
    job.completed_at = now
    job.heartbeat_at = now
    job.lease_owner = None
    job.lease_expires_at = None
    job.next_attempt_at = None


__all__ = ["RefreshFanoutResult", "execute_refresh_fanout", "publish_gallery_revision"]
