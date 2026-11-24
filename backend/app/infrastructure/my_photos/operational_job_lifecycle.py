"""Durable photo operation job lifecycle."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.settings import Settings
from app.infrastructure.database.my_photos_models import (
    MyPhotoGalleryModel,
    MyPhotoJobModel,
    MyPhotoMediaAssetModel,
)
from app.infrastructure.my_photos.operational_job_contracts import (
    OperationalJobResult,
    OperationalWorkerContext,
    _OperationalClaim,
)
from app.infrastructure.my_photos.operational_job_policy import _retry_delay
from app.infrastructure.my_photos.operational_job_queries import _locked_claim_job


async def _retry_or_fail(
    ctx: OperationalWorkerContext, claim: _OperationalClaim, settings: Settings, error_code: str
) -> OperationalJobResult:
    async with ctx.session_factory() as session:
        job = await _locked_claim_job(session, claim)
        if job is None:
            return OperationalJobResult("lease_lost")
        return await _retry_locked_job(
            session, job, claim, settings, error_code, consume_attempt=True
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
    ctx: OperationalWorkerContext, claim: _OperationalClaim, error_code: str
) -> OperationalJobResult:
    async with ctx.session_factory() as session:
        job = await _locked_claim_job(session, claim)
        if job is None:
            return OperationalJobResult("lease_lost")
        await _terminalize_job(session, job, error_code)
        await session.commit()
        return OperationalJobResult("failed")


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
    session: AsyncSession, job: MyPhotoJobModel, error_code: str, *, now: datetime | None = None
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
