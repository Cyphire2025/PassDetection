"""Bounded lease workers for gallery indexing and media preparation.

No database transaction or row lock is held while a provider is called. Every
provider result is re-bound to the exact job lease before it can mutate or
publish application state.
"""

from __future__ import annotations

import asyncio
import hashlib
import math
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal, cast

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.my_photos.errors import MyPhotosUnavailable
from app.application.my_photos.limits import MAX_MY_PHOTOS_MEDIA_BYTES
from app.application.my_photos.providers import (
    FaceIndexAsset,
    FaceIndexBatchRequest,
    FaceIndexBatchResult,
    IndexedFaceOccurrence,
    MediaAvailabilityResult,
    MediaPreparationRequest,
)
from app.application.my_photos.states import MEDIA_DELIVERY_READY_STATES
from app.core.config.settings import Settings, get_settings
from app.infrastructure.database.my_photos_models import (
    MyPhotoAssetVariantModel,
    MyPhotoFaceOccurrenceModel,
    MyPhotoGalleryManifestModel,
    MyPhotoGalleryModel,
    MyPhotoJobModel,
    MyPhotoMediaAssetModel,
)
from app.infrastructure.database.session import AsyncSessionFactory
from app.infrastructure.my_photos.providers import (
    MyPhotosProviderBundle,
    build_provider_bundle,
)
from app.infrastructure.my_photos.revision_runtime import (
    execute_refresh_fanout,
    publish_gallery_revision,
)
from app.infrastructure.my_photos.telemetry import my_photos_metrics

OperationalState = Literal[
    "succeeded", "retrying", "failed", "cancelled", "lease_busy", "lease_lost", "noop"
]
OperationalJobType = Literal[
    "index_gallery", "generate_variants", "prepare_media", "refresh_searches"
]
MediaVariant = Literal["thumbnail", "preview", "analysis", "original", "optimized"]


@dataclass(frozen=True, slots=True)
class OperationalJobResult:
    state: OperationalState
    retry_after_seconds: int | None = None
    search_run_ids: tuple[uuid.UUID, ...] = ()
    followup_job_ids: tuple[uuid.UUID, ...] = ()


@dataclass(frozen=True, slots=True)
class _OperationalClaim:
    job_id: uuid.UUID
    lease_owner: str
    job_type: OperationalJobType
    gallery_id: uuid.UUID
    media_asset_id: uuid.UUID | None
    agency_id: uuid.UUID
    group_id: uuid.UUID
    checkpoint_cursor: str | None
    target_revision: int | None
    idempotency_key: str
    request_fingerprint: str | None
    attempt_count: int
    max_attempts: int


async def execute_operational_job(
    job_id: uuid.UUID,
    *,
    settings: Settings | None = None,
    providers: MyPhotosProviderBundle | None = None,
    lease_owner: str | None = None,
    allowed_job_types: frozenset[OperationalJobType] | None = None,
) -> OperationalJobResult:
    resolved_settings = settings or get_settings()
    resolved_providers = providers or build_provider_bundle(resolved_settings)
    owner = lease_owner or f"my-photos-operation:{uuid.uuid4().hex}"
    claim_or_result = await _claim_job(
        job_id,
        owner,
        resolved_settings,
        allowed_job_types=allowed_job_types,
    )
    if isinstance(claim_or_result, OperationalJobResult):
        return claim_or_result
    claim = claim_or_result
    if claim.job_type == "refresh_searches":
        try:
            refresh = await execute_refresh_fanout(
                job_id=claim.job_id,
                lease_owner=claim.lease_owner,
                settings=resolved_settings,
            )
        except (TypeError, ValueError):
            return await _terminal_claim(claim, "REFRESH_CHECKPOINT_INVALID")
        except Exception:
            return await _retry_or_fail(
                claim,
                resolved_settings,
                "REFRESH_FANOUT_UNAVAILABLE",
            )
        return OperationalJobResult(
            "retrying" if refresh.state == "continuing" else refresh.state,
            1 if refresh.state == "continuing" else None,
            search_run_ids=refresh.search_run_ids,
        )
    if claim.job_type == "index_gallery":
        return await _execute_index_batch(claim, resolved_settings, resolved_providers)
    return await _execute_media_job(claim, resolved_settings, resolved_providers)


async def _claim_job(
    job_id: uuid.UUID,
    lease_owner: str,
    settings: Settings,
    *,
    allowed_job_types: frozenset[OperationalJobType] | None,
) -> _OperationalClaim | OperationalJobResult:
    async with AsyncSessionFactory() as session:
        job = (
            await session.execute(
                select(MyPhotoJobModel).where(MyPhotoJobModel.id == job_id).with_for_update()
            )
        ).scalar_one_or_none()
        if job is None or job.job_type == "search_passenger":
            return OperationalJobResult("noop")
        if allowed_job_types is not None and job.job_type not in allowed_job_types:
            return OperationalJobResult("noop")
        if job.status in {"succeeded", "failed", "cancelled"}:
            return OperationalJobResult("noop")
        now = datetime.now(tz=UTC)
        if job.cancellation_requested_at is not None:
            job.status = "cancelled"
            job.completed_at = now
            job.lease_owner = None
            job.lease_expires_at = None
            await session.commit()
            return OperationalJobResult("cancelled")
        if job.next_attempt_at is not None and _utc(job.next_attempt_at) > now:
            return OperationalJobResult(
                "retrying",
                max(1, math.ceil((_utc(job.next_attempt_at) - now).total_seconds())),
            )
        if (
            job.lease_owner is not None
            and job.lease_expires_at is not None
            and _utc(job.lease_expires_at) > now
        ):
            return OperationalJobResult(
                "lease_busy",
                max(1, math.ceil((_utc(job.lease_expires_at) - now).total_seconds())),
            )
        expired_lease = bool(
            job.status == "running"
            and job.lease_expires_at is not None
            and _utc(job.lease_expires_at) <= now
        )
        if expired_lease:
            job.attempt_count += 1
            job.stable_error_code = "WORKER_LEASE_EXPIRED"
        if job.attempt_count >= job.max_attempts:
            await _terminalize_job(session, job, "JOB_RETRY_EXHAUSTED", now=now)
            await session.commit()
            return OperationalJobResult("failed")
        gallery_exists = (
            await session.execute(
                select(MyPhotoGalleryModel.id).where(
                    MyPhotoGalleryModel.id == job.gallery_id,
                    MyPhotoGalleryModel.agency_id == job.agency_id,
                    MyPhotoGalleryModel.group_id == job.group_id,
                    MyPhotoGalleryModel.feature_enabled.is_(True),
                    MyPhotoGalleryModel.status.notin_(("failed", "removed")),
                )
            )
        ).scalar_one_or_none()
        if gallery_exists is None:
            await _terminalize_job(session, job, "JOB_SCOPE_STALE", now=now)
            await session.commit()
            return OperationalJobResult("failed")
        job.status = "running"
        if job.started_at is not None:
            redelivery_kind: Literal["index", "media", "refresh"] = (
                "index"
                if job.job_type == "index_gallery"
                else "refresh"
                if job.job_type == "refresh_searches"
                else "media"
            )
            my_photos_metrics.idempotent_redelivery(redelivery_kind)
        job.lease_owner = lease_owner
        job.heartbeat_at = now
        job.lease_expires_at = now + timedelta(seconds=settings.my_photos.job_lease_seconds)
        job.next_attempt_at = None
        job.started_at = job.started_at or now
        claim = _OperationalClaim(
            job_id=job.id,
            lease_owner=lease_owner,
            job_type=cast(OperationalJobType, job.job_type),
            gallery_id=job.gallery_id,
            media_asset_id=job.media_asset_id,
            agency_id=job.agency_id,
            group_id=job.group_id,
            checkpoint_cursor=job.checkpoint_cursor,
            target_revision=job.target_revision,
            idempotency_key=job.idempotency_key,
            request_fingerprint=job.request_fingerprint,
            attempt_count=job.attempt_count,
            max_attempts=job.max_attempts,
        )
        await session.commit()
        return claim


async def _execute_media_job(
    claim: _OperationalClaim,
    settings: Settings,
    providers: MyPhotosProviderBundle,
) -> OperationalJobResult:
    started = time.perf_counter()
    if claim.media_asset_id is None:
        return await _retry_or_fail(claim, settings, "MEDIA_JOB_TARGET_INVALID")
    async with AsyncSessionFactory() as session:
        asset = (
            await session.execute(
                select(MyPhotoMediaAssetModel).where(
                    MyPhotoMediaAssetModel.id == claim.media_asset_id,
                    MyPhotoMediaAssetModel.gallery_id == claim.gallery_id,
                    MyPhotoMediaAssetModel.agency_id == claim.agency_id,
                    MyPhotoMediaAssetModel.group_id == claim.group_id,
                    MyPhotoMediaAssetModel.availability_state.notin_(("failed", "removed")),
                )
            )
        ).scalar_one_or_none()
        if asset is None:
            return await _terminal_claim(claim, "MEDIA_JOB_TARGET_INVALID")
        asset_identity = asset.immutable_asset_key
    variants: tuple[MediaVariant, ...] = (
        (cast(MediaVariant, claim.checkpoint_cursor or "original"),)
        if claim.job_type == "prepare_media"
        else ("thumbnail", "preview", "analysis")
    )
    if any(
        variant not in {"thumbnail", "preview", "analysis", "original", "optimized"}
        for variant in variants
    ):
        return await _terminal_claim(claim, "MEDIA_VARIANT_INVALID")
    results: list[tuple[str, MediaAvailabilityResult]] = []
    try:

        async def prepare_variant(
            variant: MediaVariant,
        ) -> tuple[str, MediaAvailabilityResult]:
            async with asyncio.timeout(settings.my_photos.media_provider_timeout_seconds):
                provider_result = await providers.media.prepare(
                    MediaPreparationRequest(
                        tenant_scope=str(claim.agency_id),
                        group_scope=str(claim.group_id),
                        asset_identity=asset_identity,
                        variant=variant,
                        idempotency_identity=f"{claim.job_id}:{variant}",
                    )
                )
            return variant, _validated_media_result(provider_result, variant=variant)

        # At most the three fixed derivative kinds execute together; the set is
        # protocol-bounded and never grows with gallery size.
        results = list(await asyncio.gather(*(prepare_variant(variant) for variant in variants)))
    except (MyPhotosUnavailable, TimeoutError):
        my_photos_metrics.preparation_finished(
            outcome="failed", duration_ms=(time.perf_counter() - started) * 1_000
        )
        return await _retry_or_fail(claim, settings, "MEDIA_PROVIDER_UNAVAILABLE")
    except (ValueError, TypeError):
        my_photos_metrics.preparation_finished(
            outcome="failed", duration_ms=(time.perf_counter() - started) * 1_000
        )
        return await _terminal_claim(claim, "MEDIA_PROVIDER_RESULT_INVALID")
    except Exception:
        my_photos_metrics.preparation_finished(
            outcome="failed", duration_ms=(time.perf_counter() - started) * 1_000
        )
        return await _retry_or_fail(claim, settings, "MEDIA_PROVIDER_UNAVAILABLE")
    outcome = await _finalize_media(claim, results, settings)
    my_photos_metrics.preparation_finished(
        outcome=(
            "available"
            if outcome.state == "succeeded"
            else "waiting"
            if outcome.state == "retrying"
            else "failed"
        ),
        duration_ms=(time.perf_counter() - started) * 1_000,
    )
    return outcome


async def _execute_index_batch(
    claim: _OperationalClaim,
    settings: Settings,
    providers: MyPhotosProviderBundle,
) -> OperationalJobResult:
    if claim.target_revision is None:
        return await _terminal_claim(claim, "INDEX_REVISION_MISSING")
    checkpoint_rank = int(claim.checkpoint_cursor or "-1")
    async with AsyncSessionFactory() as session:
        gallery = (
            await session.execute(
                select(MyPhotoGalleryModel).where(
                    MyPhotoGalleryModel.id == claim.gallery_id,
                    MyPhotoGalleryModel.agency_id == claim.agency_id,
                    MyPhotoGalleryModel.group_id == claim.group_id,
                )
            )
        ).scalar_one_or_none()
        if gallery is None:
            return await _terminal_claim(claim, "INDEX_COLLECTION_MISSING")
        if providers.provider_name == "aws":
            manifest = (
                await session.execute(
                    select(MyPhotoGalleryManifestModel).where(
                        MyPhotoGalleryManifestModel.gallery_id == claim.gallery_id,
                        MyPhotoGalleryManifestModel.agency_id == claim.agency_id,
                        MyPhotoGalleryManifestModel.group_id == claim.group_id,
                        MyPhotoGalleryManifestModel.manifest_identity == claim.idempotency_key,
                        MyPhotoGalleryManifestModel.target_revision == claim.target_revision,
                        MyPhotoGalleryManifestModel.content_fingerprint
                        == claim.request_fingerprint,
                        MyPhotoGalleryManifestModel.status == "indexing",
                    )
                )
            ).scalar_one_or_none()
            if manifest is None:
                return await _terminal_claim(claim, "INDEX_MANIFEST_INVALID")
            collection_reference = manifest.provider_collection_reference
            index_version = manifest.target_revision
        else:
            if gallery.provider_collection_reference is None:
                return await _terminal_claim(claim, "INDEX_COLLECTION_MISSING")
            collection_reference = gallery.provider_collection_reference
            index_version = gallery.face_index_version
        assets = list(
            (
                await session.execute(
                    select(MyPhotoMediaAssetModel)
                    .where(
                        MyPhotoMediaAssetModel.gallery_id == claim.gallery_id,
                        MyPhotoMediaAssetModel.agency_id == claim.agency_id,
                        MyPhotoMediaAssetModel.group_id == claim.group_id,
                        MyPhotoMediaAssetModel.published_revision == claim.target_revision,
                        MyPhotoMediaAssetModel.sort_rank > checkpoint_rank,
                        MyPhotoMediaAssetModel.processing_state.notin_(("failed", "removed")),
                    )
                    .order_by(MyPhotoMediaAssetModel.sort_rank, MyPhotoMediaAssetModel.id)
                    .limit(settings.my_photos.job_batch_size)
                )
            ).scalars()
        )
    if not assets:
        return await _publish_index_if_complete(claim, settings)
    async with AsyncSessionFactory() as session:
        analysis_variants = await _latest_ready_analysis_variants(
            session,
            assets=assets,
            agency_id=claim.agency_id,
            group_id=claim.group_id,
        )
    if len(analysis_variants) != len(assets):
        # Variant generation and indexing use separate durable queues. A ready
        # analysis derivative is an explicit prerequisite; never fabricate a
        # media locator or send an original to the face-index provider.
        return await _retry_or_fail(claim, settings, "INDEX_ANALYSIS_NOT_READY")
    request_assets = tuple(
        FaceIndexAsset(
            asset_identity=asset.immutable_asset_key,
            analysis_media_reference=cast(str, analysis_variants[asset.id].storage_reference),
            idempotency_identity=(f"index:{claim.gallery_id}:{index_version}:{asset.id}"),
        )
        for asset in assets
    )
    try:
        async with asyncio.timeout(settings.my_photos.face_search_provider_timeout_seconds):
            raw_result = await providers.face_search.index_faces(
                FaceIndexBatchRequest(
                    tenant_scope=str(claim.agency_id),
                    group_scope=str(claim.group_id),
                    collection_reference=collection_reference,
                    index_version=index_version,
                    assets=request_assets,
                )
            )
        result = _validated_index_result(raw_result, request_assets)
    except (MyPhotosUnavailable, TimeoutError):
        return await _retry_or_fail(claim, settings, "INDEX_PROVIDER_UNAVAILABLE")
    except (ValueError, TypeError):
        return await _terminal_claim(claim, "INDEX_PROVIDER_RESULT_INVALID")
    except Exception:
        return await _retry_or_fail(claim, settings, "INDEX_PROVIDER_UNAVAILABLE")
    return await _finalize_index_batch(claim, assets, result, settings)


async def _finalize_media(
    claim: _OperationalClaim,
    results: list[tuple[str, MediaAvailabilityResult]],
    settings: Settings,
) -> OperationalJobResult:
    async with AsyncSessionFactory() as session:
        rows = await _locked_job_and_asset(session, claim)
        if rows is None:
            return OperationalJobResult("lease_lost")
        job, asset = rows
        if any(result.state not in MEDIA_DELIVERY_READY_STATES for _, result in results):
            preparing = results[-1][1].state
            asset.availability_state = preparing
            job.attempt_count = 0
            return await _retry_locked_job(
                session,
                job,
                claim,
                settings,
                "MEDIA_PREPARING",
                delay=settings.my_photos.job_retry_max_seconds,
                consume_attempt=False,
            )
        for variant, result in results:
            if variant == "original":
                if (
                    result.byte_size != asset.byte_size
                    or result.checksum_sha256 != asset.checksum_sha256
                ):
                    await _terminalize_job(session, job, "MEDIA_INTEGRITY_CHANGED")
                    await session.commit()
                    return OperationalJobResult("failed")
                asset.storage_reference = result.storage_reference
                asset.availability_state = "delivery_available"
                continue
            existing = (
                await session.execute(
                    select(MyPhotoAssetVariantModel).where(
                        MyPhotoAssetVariantModel.media_asset_id == asset.id,
                        MyPhotoAssetVariantModel.variant_kind == variant,
                        MyPhotoAssetVariantModel.delivery_version == result.delivery_version,
                    )
                )
            ).scalar_one_or_none()
            if existing is None:
                session.add(
                    MyPhotoAssetVariantModel(
                        media_asset_id=asset.id,
                        agency_id=asset.agency_id,
                        group_id=asset.group_id,
                        variant_kind=variant,
                        storage_reference=result.storage_reference,
                        mime_type=result.content_type,
                        width=result.width,
                        height=result.height,
                        byte_size=result.byte_size,
                        checksum_sha256=result.checksum_sha256,
                        availability_state=result.state,
                        delivery_version=result.delivery_version,
                    )
                )
        if claim.job_type == "generate_variants":
            asset.processing_state = "processing"
            if asset.availability_state in {
                "registered",
                "awaiting_upload",
                "processing",
                "indexed",
            }:
                asset.availability_state = "preview_available"
        now = datetime.now(tz=UTC)
        job.status = "succeeded"
        job.attempt_count = 0
        job.processed_count = job.total_count
        job.succeeded_count = job.total_count
        job.completed_at = now
        job.heartbeat_at = now
        job.lease_owner = None
        job.lease_expires_at = None
        job.stable_error_code = None
        await session.commit()
        my_photos_metrics.job("succeeded")
        return OperationalJobResult("succeeded")


async def _finalize_index_batch(
    claim: _OperationalClaim,
    assets: list[MyPhotoMediaAssetModel],
    result: FaceIndexBatchResult,
    settings: Settings,
) -> OperationalJobResult:
    asset_ids = tuple(asset.id for asset in assets)
    failed = {failure.asset_identity for failure in result.failures}
    async with AsyncSessionFactory() as session:
        job = (
            await session.execute(
                select(MyPhotoJobModel)
                .where(
                    MyPhotoJobModel.id == claim.job_id,
                    MyPhotoJobModel.status == "running",
                    MyPhotoJobModel.lease_owner == claim.lease_owner,
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if job is None:
            return OperationalJobResult("lease_lost")
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
                        MyPhotoFaceOccurrenceModel.index_version
                        == (
                            select(MyPhotoGalleryModel.face_index_version)
                            .where(MyPhotoGalleryModel.id == claim.gallery_id)
                            .scalar_subquery()
                        ),
                        MyPhotoFaceOccurrenceModel.provider_face_reference.in_(
                            tuple(
                                occurrence.provider_face_reference
                                for occurrence in result.occurrences
                            )
                        ),
                    )
                )
            ).scalars()
        )
        gallery = (
            await session.execute(
                select(MyPhotoGalleryModel)
                .where(MyPhotoGalleryModel.id == claim.gallery_id)
                .with_for_update()
            )
        ).scalar_one()
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
                    index_version=gallery.face_index_version,
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
            succeeded=len(managed_assets) - len(failed),
            failed=len(failed),
        )
        my_photos_metrics.face_occurrences(len(result.occurrences))
        processed = len(managed_assets)
        job.processed_count = min(job.total_count, job.processed_count + processed)
        job.attempt_count = 0
        job.succeeded_count += processed - len(failed)
        job.failed_count += len(failed)
        job.checkpoint_cursor = str(managed_assets[-1].sort_rank)
        gallery.indexed_asset_count = int(
            (
                await session.execute(
                    select(func.count(MyPhotoMediaAssetModel.id)).where(
                        MyPhotoMediaAssetModel.gallery_id == gallery.id,
                        MyPhotoMediaAssetModel.published_revision <= claim.target_revision,
                        MyPhotoMediaAssetModel.processing_state == "indexed",
                    )
                )
            ).scalar_one()
        )
        gallery.failed_asset_count = int(
            (
                await session.execute(
                    select(func.count(MyPhotoMediaAssetModel.id)).where(
                        MyPhotoMediaAssetModel.gallery_id == gallery.id,
                        MyPhotoMediaAssetModel.published_revision <= claim.target_revision,
                        MyPhotoMediaAssetModel.processing_state == "failed",
                    )
                )
            ).scalar_one()
        )
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
                session,
                gallery=gallery,
                index_job=job,
                settings=settings,
                published_at=now,
            )
            await session.commit()
            return OperationalJobResult(
                "succeeded",
                followup_job_ids=(followup_id,) if followup_id is not None else (),
            )
        return await _retry_locked_job(
            session,
            job,
            claim,
            settings,
            None,
            delay=1,
            consume_attempt=False,
        )


async def _publish_index_if_complete(
    claim: _OperationalClaim, settings: Settings
) -> OperationalJobResult:
    async with AsyncSessionFactory() as session:
        job = (
            await session.execute(
                select(MyPhotoJobModel)
                .where(
                    MyPhotoJobModel.id == claim.job_id,
                    MyPhotoJobModel.status == "running",
                    MyPhotoJobModel.lease_owner == claim.lease_owner,
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if job is None:
            return OperationalJobResult("lease_lost")
        if job.processed_count < job.total_count:
            await _terminalize_job(session, job, "INDEX_ASSET_COUNT_MISMATCH")
            await session.commit()
            return OperationalJobResult("failed")
        if not _index_publication_allowed(job, settings):
            await _terminalize_job(session, job, "INDEX_COMPLETENESS_FAILED")
            await session.commit()
            return OperationalJobResult("failed")
        gallery = (
            await session.execute(
                select(MyPhotoGalleryModel)
                .where(MyPhotoGalleryModel.id == claim.gallery_id)
                .with_for_update()
            )
        ).scalar_one()
        now = datetime.now(tz=UTC)
        job.status = "succeeded"
        job.attempt_count = 0
        job.completed_at = now
        job.lease_owner = None
        job.lease_expires_at = None
        followup_id = await publish_gallery_revision(
            session,
            gallery=gallery,
            index_job=job,
            settings=settings,
            published_at=now,
        )
        await session.commit()
        return OperationalJobResult(
            "succeeded",
            followup_job_ids=(followup_id,) if followup_id is not None else (),
        )


async def _retry_or_fail(
    claim: _OperationalClaim,
    settings: Settings,
    error_code: str,
) -> OperationalJobResult:
    async with AsyncSessionFactory() as session:
        job = (
            await session.execute(
                select(MyPhotoJobModel)
                .where(
                    MyPhotoJobModel.id == claim.job_id,
                    MyPhotoJobModel.status == "running",
                    MyPhotoJobModel.lease_owner == claim.lease_owner,
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if job is None:
            return OperationalJobResult("lease_lost")
        return await _retry_locked_job(
            session,
            job,
            claim,
            settings,
            error_code,
            consume_attempt=True,
        )


async def _retry_locked_job(
    session: AsyncSession,
    job: MyPhotoJobModel,
    claim: _OperationalClaim,
    settings: Settings,
    error_code: str | None,
    *,
    delay: int | None = None,
    consume_attempt: bool,
) -> OperationalJobResult:
    now = datetime.now(tz=UTC)
    if consume_attempt:
        job.attempt_count += 1
        if job.attempt_count >= job.max_attempts:
            await _terminalize_job(session, job, error_code or "JOB_RETRY_EXHAUSTED", now=now)
            await session.commit()
            return OperationalJobResult("failed")
    retry_delay = delay or _retry_delay(job.id, job.attempt_count, settings)
    job.status = "retrying"
    job.stable_error_code = error_code
    job.next_attempt_at = now + timedelta(seconds=retry_delay)
    job.lease_owner = None
    job.lease_expires_at = None
    job.heartbeat_at = now
    await session.commit()
    return OperationalJobResult("retrying", retry_delay)


async def _terminal_claim(
    claim: _OperationalClaim,
    error_code: str,
) -> OperationalJobResult:
    async with AsyncSessionFactory() as session:
        job = (
            await session.execute(
                select(MyPhotoJobModel)
                .where(
                    MyPhotoJobModel.id == claim.job_id,
                    MyPhotoJobModel.lease_owner == claim.lease_owner,
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if job is None:
            return OperationalJobResult("lease_lost")
        await _terminalize_job(session, job, error_code)
        await session.commit()
        return OperationalJobResult("failed")


async def _locked_job_and_asset(
    session: AsyncSession,
    claim: _OperationalClaim,
) -> tuple[MyPhotoJobModel, MyPhotoMediaAssetModel] | None:
    job = (
        await session.execute(
            select(MyPhotoJobModel)
            .where(
                MyPhotoJobModel.id == claim.job_id,
                MyPhotoJobModel.status == "running",
                MyPhotoJobModel.lease_owner == claim.lease_owner,
                MyPhotoJobModel.cancellation_requested_at.is_(None),
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if job is None or claim.media_asset_id is None:
        return None
    asset = (
        await session.execute(
            select(MyPhotoMediaAssetModel)
            .where(
                MyPhotoMediaAssetModel.id == claim.media_asset_id,
                MyPhotoMediaAssetModel.agency_id == claim.agency_id,
                MyPhotoMediaAssetModel.group_id == claim.group_id,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    return (job, asset) if asset is not None else None


def _validated_media_result(
    result: MediaAvailabilityResult,
    *,
    variant: str,
) -> MediaAvailabilityResult:
    if result.delivery_version < 1:
        raise ValueError("Invalid media delivery version")
    if result.state not in MEDIA_DELIVERY_READY_STATES:
        if any(
            value is not None
            for value in (
                result.byte_size,
                result.checksum_sha256,
                result.storage_reference,
                result.content_type,
                result.width,
                result.height,
            )
        ):
            raise ValueError("Preparing media result carried delivery metadata")
        return result
    if (
        result.byte_size is None
        or not 1 <= result.byte_size <= MAX_MY_PHOTOS_MEDIA_BYTES
        or result.checksum_sha256 is None
        or len(result.checksum_sha256) != 64
        or any(character not in "0123456789abcdef" for character in result.checksum_sha256)
        or result.storage_reference is None
        or not _valid_opaque(result.storage_reference, 4_096)
        or result.content_type not in {"image/jpeg", "image/png", "image/webp"}
        or result.width is None
        or result.height is None
        or not 1 <= result.width <= 100_000
        or not 1 <= result.height <= 100_000
    ):
        raise ValueError(f"Invalid {variant} media provider result")
    return result


def _validated_index_result(
    result: FaceIndexBatchResult,
    requested: tuple[FaceIndexAsset, ...],
) -> FaceIndexBatchResult:
    identities = {asset.asset_identity for asset in requested}
    if len(result.occurrences) > len(requested) * 100 or len(result.failures) > len(requested):
        raise ValueError("Unbounded index provider result")
    seen_references: set[str] = set()
    seen_idempotency: set[tuple[str, str]] = set()
    occurrence_assets: set[str] = set()
    for occurrence in result.occurrences:
        _validate_occurrence(occurrence, identities)
        occurrence_key = (occurrence.asset_identity, occurrence.idempotency_identity)
        if occurrence.provider_face_reference in seen_references:
            raise ValueError("Duplicate provider face reference")
        if occurrence_key in seen_idempotency:
            raise ValueError("Duplicate indexed face idempotency identity")
        seen_references.add(occurrence.provider_face_reference)
        seen_idempotency.add(occurrence_key)
        occurrence_assets.add(occurrence.asset_identity)
    failure_assets: set[str] = set()
    for failure in result.failures:
        if (
            failure.asset_identity not in identities
            or failure.asset_identity in failure_assets
            or failure.asset_identity in occurrence_assets
            or not _valid_error(failure.stable_error_code)
        ):
            raise ValueError("Invalid index failure")
        failure_assets.add(failure.asset_identity)
    return result


async def _latest_ready_analysis_variants(
    session: AsyncSession,
    *,
    assets: list[MyPhotoMediaAssetModel],
    agency_id: uuid.UUID,
    group_id: uuid.UUID,
) -> dict[uuid.UUID, MyPhotoAssetVariantModel]:
    """Load one current, provider-ready analysis derivative per bounded batch."""

    asset_ids = tuple(asset.id for asset in assets)
    if not asset_ids:
        return {}
    now = datetime.now(tz=UTC)
    latest = (
        select(
            MyPhotoAssetVariantModel.media_asset_id.label("asset_id"),
            func.max(MyPhotoAssetVariantModel.delivery_version).label("delivery_version"),
        )
        .where(
            MyPhotoAssetVariantModel.media_asset_id.in_(asset_ids),
            MyPhotoAssetVariantModel.agency_id == agency_id,
            MyPhotoAssetVariantModel.group_id == group_id,
            MyPhotoAssetVariantModel.variant_kind == "analysis",
            MyPhotoAssetVariantModel.availability_state.in_(tuple(MEDIA_DELIVERY_READY_STATES)),
            MyPhotoAssetVariantModel.storage_reference.is_not(None),
            or_(
                MyPhotoAssetVariantModel.expires_at.is_(None),
                MyPhotoAssetVariantModel.expires_at > now,
            ),
        )
        .group_by(MyPhotoAssetVariantModel.media_asset_id)
        .subquery()
    )
    rows = list(
        (
            await session.execute(
                select(MyPhotoAssetVariantModel).join(
                    latest,
                    and_(
                        latest.c.asset_id == MyPhotoAssetVariantModel.media_asset_id,
                        latest.c.delivery_version == MyPhotoAssetVariantModel.delivery_version,
                    ),
                )
            )
        ).scalars()
    )
    return {row.media_asset_id: row for row in rows}


def _validate_occurrence(
    occurrence: IndexedFaceOccurrence,
    identities: set[str],
) -> None:
    box = occurrence.bounding_box
    if (
        occurrence.asset_identity not in identities
        or not _valid_opaque(occurrence.provider_face_reference, 512)
        or not _valid_opaque(occurrence.idempotency_identity, 128)
        or not _valid_opaque(occurrence.provider_model_version, 64)
        or not 0 <= box.left <= 1
        or not 0 <= box.top <= 1
        or not 0 < box.width <= 1
        or not 0 < box.height <= 1
        or box.left + box.width > 1.000001
        or box.top + box.height > 1.000001
        or (occurrence.quality_score is not None and not 0 <= occurrence.quality_score <= 100)
    ):
        raise ValueError("Invalid indexed face occurrence")


def _retry_delay(job_id: uuid.UUID, attempt_count: int, settings: Settings) -> int:
    base = min(
        settings.my_photos.job_retry_max_seconds,
        settings.my_photos.job_retry_base_seconds * (2 ** min(max(attempt_count - 1, 0), 8)),
    )
    digest = hashlib.sha256(f"{job_id}:{attempt_count}".encode()).digest()
    jitter = int.from_bytes(digest[:2], "big") % max(1, base // 2 + 1)
    return int(min(settings.my_photos.job_retry_max_seconds, base + jitter))


def _terminal_job(job: MyPhotoJobModel, now: datetime, error_code: str) -> None:
    job.status = "failed"
    job.stable_error_code = error_code[:64]
    job.error_detail = "Job stopped with a stable provider-safe category."
    job.completed_at = now
    job.heartbeat_at = now
    job.lease_owner = None
    job.lease_expires_at = None
    job.next_attempt_at = None


async def _terminalize_job(
    session: AsyncSession,
    job: MyPhotoJobModel,
    error_code: str,
    *,
    now: datetime | None = None,
) -> None:
    terminal_at = now or datetime.now(tz=UTC)
    _terminal_job(job, terminal_at, error_code)
    if job.media_asset_id is not None:
        asset = (
            await session.execute(
                select(MyPhotoMediaAssetModel)
                .where(
                    MyPhotoMediaAssetModel.id == job.media_asset_id,
                    MyPhotoMediaAssetModel.agency_id == job.agency_id,
                    MyPhotoMediaAssetModel.group_id == job.group_id,
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if asset is not None and asset.processing_state != "removed":
            asset.availability_state = "failed"
            if job.job_type == "generate_variants":
                asset.processing_state = "failed"
    elif job.job_type == "index_gallery":
        gallery = (
            await session.execute(
                select(MyPhotoGalleryModel)
                .where(MyPhotoGalleryModel.id == job.gallery_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if gallery is not None and gallery.status not in {"removed", "ready"}:
            gallery.status = "failed"


def _valid_opaque(value: str, maximum: int) -> bool:
    return bool(
        value
        and len(value) <= maximum
        and value == value.strip()
        and value.isprintable()
        and "://" not in value
    )


def _valid_error(value: str) -> bool:
    return bool(
        value and len(value) <= 64 and value == value.strip() and value.replace("_", "").isalnum()
    )


def _index_publication_allowed(job: MyPhotoJobModel, settings: Settings) -> bool:
    if (
        job.total_count <= 0
        or job.processed_count != job.total_count
        or job.succeeded_count + job.failed_count != job.total_count
        or job.succeeded_count <= 0
    ):
        return False
    return bool((job.failed_count / job.total_count) <= settings.my_photos.index_max_failure_ratio)


def _utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


__all__ = ["OperationalJobResult", "execute_operational_job"]
