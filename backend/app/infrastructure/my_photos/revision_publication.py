"""Atomic indexed revision publication and durable refresh scheduling."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.settings import Settings
from app.infrastructure.database.my_photos_models import (
    MyPhotoEnrollmentModel,
    MyPhotoGalleryManifestModel,
    MyPhotoGalleryModel,
    MyPhotoJobModel,
    MyPhotoMediaAssetModel,
)


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
    published_counts = (
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
                MyPhotoMediaAssetModel.published_revision <= target_revision,
                MyPhotoMediaAssetModel.processing_state != "removed",
            )
        )
    ).one()
    # Publish all three counters together. Staged indexing progress belongs to
    # its job; publishing it against the preceding revision's total can violate
    # the gallery count constraint before the revision is ready.
    gallery.total_asset_count = int(published_counts[0])
    gallery.indexed_asset_count = int(published_counts[1])
    gallery.failed_asset_count = int(published_counts[2])

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


publish_gallery_revision.__module__ = "app.infrastructure.my_photos.revision_runtime"
