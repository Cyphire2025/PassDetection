"""Durable photo operation media jobs."""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime
from typing import cast

from sqlalchemy import select

from app.application.my_photos.errors import MyPhotosUnavailable
from app.application.my_photos.providers import MediaAvailabilityResult, MediaPreparationRequest
from app.application.my_photos.states import MEDIA_DELIVERY_READY_STATES
from app.core.config.settings import Settings
from app.infrastructure.database.my_photos_models import (
    MyPhotoAssetVariantModel,
    MyPhotoMediaAssetModel,
)
from app.infrastructure.my_photos.operational_job_contracts import (
    MediaVariant,
    OperationalJobResult,
    OperationalWorkerContext,
    _OperationalClaim,
)
from app.infrastructure.my_photos.operational_job_lifecycle import (
    _retry_locked_job,
    _retry_or_fail,
    _terminal_claim,
    _terminalize_job,
)
from app.infrastructure.my_photos.operational_job_policy import _validated_media_result
from app.infrastructure.my_photos.operational_job_queries import _locked_job_and_asset
from app.infrastructure.my_photos.provider_tasks import gather_provider_results
from app.infrastructure.my_photos.providers import MyPhotosProviderBundle
from app.infrastructure.my_photos.telemetry import my_photos_metrics


async def _execute_media_job(
    ctx: OperationalWorkerContext,
    claim: _OperationalClaim,
    settings: Settings,
    providers: MyPhotosProviderBundle,
) -> OperationalJobResult:
    started = time.perf_counter()
    if claim.media_asset_id is None:
        return await _retry_or_fail(ctx, claim, settings, "MEDIA_JOB_TARGET_INVALID")
    async with ctx.session_factory() as session:
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
            return await _terminal_claim(ctx, claim, "MEDIA_JOB_TARGET_INVALID")
        asset_identity = asset.immutable_asset_key
    variants: tuple[MediaVariant, ...] = (
        (cast(MediaVariant, claim.checkpoint_cursor or "original"),)
        if claim.job_type == "prepare_media"
        else ("thumbnail", "preview", "analysis")
    )
    if any(
        (
            variant not in {"thumbnail", "preview", "analysis", "original", "optimized"}
            for variant in variants
        )
    ):
        return await _terminal_claim(ctx, claim, "MEDIA_VARIANT_INVALID")
    results: list[tuple[str, MediaAvailabilityResult]] = []
    try:

        async def prepare_variant(variant: MediaVariant) -> tuple[str, MediaAvailabilityResult]:
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
            return (variant, _validated_media_result(provider_result, variant=variant))

        results = await gather_provider_results([prepare_variant(variant) for variant in variants])
    except (MyPhotosUnavailable, TimeoutError):
        my_photos_metrics.preparation_finished(
            outcome="failed", duration_ms=(time.perf_counter() - started) * 1000
        )
        return await _retry_or_fail(ctx, claim, settings, "MEDIA_PROVIDER_UNAVAILABLE")
    except (ValueError, TypeError):
        my_photos_metrics.preparation_finished(
            outcome="failed", duration_ms=(time.perf_counter() - started) * 1000
        )
        return await _terminal_claim(ctx, claim, "MEDIA_PROVIDER_RESULT_INVALID")
    except Exception:
        my_photos_metrics.preparation_finished(
            outcome="failed", duration_ms=(time.perf_counter() - started) * 1000
        )
        return await _retry_or_fail(ctx, claim, settings, "MEDIA_PROVIDER_UNAVAILABLE")
    outcome = await _finalize_media(ctx, claim, results, settings)
    my_photos_metrics.preparation_finished(
        outcome="available"
        if outcome.state == "succeeded"
        else "waiting"
        if outcome.state == "retrying"
        else "failed",
        duration_ms=(time.perf_counter() - started) * 1000,
    )
    return outcome


async def _finalize_media(
    ctx: OperationalWorkerContext,
    claim: _OperationalClaim,
    results: list[tuple[str, MediaAvailabilityResult]],
    settings: Settings,
) -> OperationalJobResult:
    async with ctx.session_factory() as session:
        rows = await _locked_job_and_asset(session, claim)
        if rows is None:
            return OperationalJobResult("lease_lost")
        job, asset = rows
        if any((result.state not in MEDIA_DELIVERY_READY_STATES for _, result in results)):
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
