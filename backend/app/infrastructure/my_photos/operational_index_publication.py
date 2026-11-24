"""Durable photo operation index publication."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select

from app.application.my_photos.providers import FaceIndexBatchResult
from app.core.config.settings import Settings
from app.infrastructure.database.my_photos_models import (
    MyPhotoFaceOccurrenceModel,
    MyPhotoMediaAssetModel,
)
from app.infrastructure.my_photos.operational_job_contracts import (
    OperationalJobResult,
    OperationalWorkerContext,
    _OperationalClaim,
)
from app.infrastructure.my_photos.operational_job_lifecycle import (
    _retry_locked_job,
    _terminalize_job,
)
from app.infrastructure.my_photos.operational_job_policy import _index_publication_allowed
from app.infrastructure.my_photos.operational_job_queries import _locked_current_job_scope
from app.infrastructure.my_photos.revision_runtime import publish_gallery_revision
from app.infrastructure.my_photos.telemetry import my_photos_metrics


async def _finalize_index_batch(
    ctx: OperationalWorkerContext,
    claim: _OperationalClaim,
    assets: list[MyPhotoMediaAssetModel],
    result: FaceIndexBatchResult,
    settings: Settings,
) -> OperationalJobResult:
    asset_ids = tuple((asset.id for asset in assets))
    failed = {failure.asset_identity for failure in result.failures}
    async with ctx.session_factory() as session:
        scope = await _locked_current_job_scope(session, claim)
        if scope is None:
            return OperationalJobResult("lease_lost")
        job, gallery = scope
        managed_assets = list(
            (
                await session.execute(
                    select(MyPhotoMediaAssetModel)
                    .where(
                        MyPhotoMediaAssetModel.id.in_(asset_ids),
                        MyPhotoMediaAssetModel.gallery_id == claim.gallery_id,
                        MyPhotoMediaAssetModel.agency_id == claim.agency_id,
                        MyPhotoMediaAssetModel.group_id == claim.group_id,
                        MyPhotoMediaAssetModel.published_revision == claim.target_revision,
                    )
                    .order_by(MyPhotoMediaAssetModel.sort_rank, MyPhotoMediaAssetModel.id)
                    .with_for_update()
                )
            ).scalars()
        )
        if len(managed_assets) != len(asset_ids):
            await _terminalize_job(session, job, "INDEX_BATCH_SCOPE_CHANGED")
            await session.commit()
            return OperationalJobResult("failed")
        by_identity = {asset.immutable_asset_key: asset for asset in managed_assets}
        existing_references = set(
            (
                await session.execute(
                    select(MyPhotoFaceOccurrenceModel.provider_face_reference).where(
                        MyPhotoFaceOccurrenceModel.agency_id == claim.agency_id,
                        MyPhotoFaceOccurrenceModel.group_id == claim.group_id,
                        MyPhotoFaceOccurrenceModel.index_version == claim.target_revision,
                        MyPhotoFaceOccurrenceModel.provider_face_reference.in_(
                            tuple(
                                (
                                    occurrence.provider_face_reference
                                    for occurrence in result.occurrences
                                )
                            )
                        ),
                    )
                )
            ).scalars()
        )
        if claim.target_revision is None or gallery.published_revision + 1 != claim.target_revision:
            await _terminalize_job(session, job, "INDEX_REVISION_STALE")
            await session.commit()
            return OperationalJobResult("failed")
        for occurrence in result.occurrences:
            if occurrence.provider_face_reference in existing_references:
                continue
            asset = by_identity[occurrence.asset_identity]
            session.add(
                MyPhotoFaceOccurrenceModel(
                    media_asset_id=asset.id,
                    agency_id=claim.agency_id,
                    group_id=claim.group_id,
                    provider_name=gallery.provider_name or "provider",
                    provider_face_reference=occurrence.provider_face_reference,
                    idempotency_identity=occurrence.idempotency_identity,
                    bounding_left=occurrence.bounding_box.left,
                    bounding_top=occurrence.bounding_box.top,
                    bounding_width=occurrence.bounding_box.width,
                    bounding_height=occurrence.bounding_box.height,
                    quality_score=occurrence.quality_score,
                    quality_class=None,
                    provider_model_version=occurrence.provider_model_version,
                    index_version=claim.target_revision,
                    active=True,
                )
            )
        for asset in managed_assets:
            if asset.immutable_asset_key in failed:
                asset.processing_state = "failed"
            else:
                asset.processing_state = "indexed"
        await session.flush()
        my_photos_metrics.indexing_assets(
            succeeded=len(managed_assets) - len(failed), failed=len(failed)
        )
        my_photos_metrics.face_occurrences(len(result.occurrences))
        processed = len(managed_assets)
        job.processed_count = min(job.total_count, job.processed_count + processed)
        job.attempt_count = 0
        job.succeeded_count += processed - len(failed)
        job.failed_count += len(failed)
        job.checkpoint_cursor = str(managed_assets[-1].sort_rank)
        if job.processed_count >= job.total_count:
            if not _index_publication_allowed(job, settings):
                await _terminalize_job(session, job, "INDEX_COMPLETENESS_FAILED")
                await session.commit()
                return OperationalJobResult("failed")
            now = datetime.now(tz=UTC)
            job.status = "succeeded"
            job.completed_at = now
            job.lease_owner = None
            job.lease_expires_at = None
            followup_id = await publish_gallery_revision(
                session, gallery=gallery, index_job=job, settings=settings, published_at=now
            )
            await session.commit()
            return OperationalJobResult(
                "succeeded", followup_job_ids=(followup_id,) if followup_id is not None else ()
            )
        return await _retry_locked_job(
            session, job, claim, settings, None, delay=1, consume_attempt=False
        )


async def _publish_index_if_complete(
    ctx: OperationalWorkerContext, claim: _OperationalClaim, settings: Settings
) -> OperationalJobResult:
    async with ctx.session_factory() as session:
        scope = await _locked_current_job_scope(session, claim)
        if scope is None:
            return OperationalJobResult("lease_lost")
        job, gallery = scope
        if job.processed_count < job.total_count:
            await _terminalize_job(session, job, "INDEX_ASSET_COUNT_MISMATCH")
            await session.commit()
            return OperationalJobResult("failed")
        if not _index_publication_allowed(job, settings):
            await _terminalize_job(session, job, "INDEX_COMPLETENESS_FAILED")
            await session.commit()
            return OperationalJobResult("failed")
        now = datetime.now(tz=UTC)
        job.status = "succeeded"
        job.attempt_count = 0
        job.completed_at = now
        job.lease_owner = None
        job.lease_expires_at = None
        followup_id = await publish_gallery_revision(
            session, gallery=gallery, index_job=job, settings=settings, published_at=now
        )
        await session.commit()
        return OperationalJobResult(
            "succeeded", followup_job_ids=(followup_id,) if followup_id is not None else ()
        )
