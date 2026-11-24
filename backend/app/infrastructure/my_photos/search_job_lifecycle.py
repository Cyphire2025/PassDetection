"""Durable passenger-search failure, retry and privacy-safe audit transitions."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.settings import Settings
from app.infrastructure.database.my_photos_models import MyPhotoJobModel, MyPhotoSearchRunModel
from app.infrastructure.my_photos.audit import record_my_photos_audit
from app.infrastructure.my_photos.search_job_contracts import (
    SearchJobExecutionResult,
    SearchWorkerContext,
    _SearchClaim,
)
from app.infrastructure.my_photos.search_job_policy import _retry_delay, _stable_error_code
from app.infrastructure.my_photos.search_job_queries import _locked_claim_rows
from app.infrastructure.my_photos.telemetry import my_photos_metrics


async def _retry_or_fail(
    ctx: SearchWorkerContext,
    claim: _SearchClaim,
    *,
    error_code: str,
    settings: Settings,
) -> SearchJobExecutionResult:
    async with ctx.session_factory() as session:
        search, job = await _locked_claim_rows(session, claim)
        if search is None or job is None:
            my_photos_metrics.job("lease_lost")
            return SearchJobExecutionResult(state="lease_lost", retry_after_seconds=1)
        now = datetime.now(tz=UTC)
        if claim.attempt_count >= claim.max_attempts:
            _mark_terminal_failure(search, job, now, error_code)
            await _audit_search(session, search, "failed", settings)
            await session.commit()
            my_photos_metrics.job("failed")
            return SearchJobExecutionResult(state="failed")
        retry_after = _retry_delay(claim, settings)
        search.status = "queued"
        search.stable_error_code = error_code
        search.lease_owner = None
        search.lease_expires_at = None
        search.heartbeat_at = now
        job.status = "retrying"
        job.stable_error_code = error_code
        job.error_detail = "Search provider returned a retry-safe stable category."
        job.next_attempt_at = now + timedelta(seconds=retry_after)
        job.lease_owner = None
        job.lease_expires_at = None
        job.heartbeat_at = now
        await session.commit()
        my_photos_metrics.job("retrying")
        return SearchJobExecutionResult("retrying", retry_after)


async def _terminal_claim_failure(
    ctx: SearchWorkerContext,
    claim: _SearchClaim,
    error_code: str,
) -> SearchJobExecutionResult:
    async with ctx.session_factory() as session:
        search, job = await _locked_claim_rows(session, claim)
        if search is None or job is None:
            my_photos_metrics.job("lease_lost")
            return SearchJobExecutionResult(state="lease_lost", retry_after_seconds=1)
        _mark_terminal_failure(search, job, datetime.now(tz=UTC), error_code)
        await session.commit()
        my_photos_metrics.job("failed")
        return SearchJobExecutionResult(state="failed")


def _mark_terminal_failure(
    search: MyPhotoSearchRunModel,
    job: MyPhotoJobModel,
    now: datetime,
    error_code: str,
) -> None:
    stable = _stable_error_code(error_code)
    search.status = "failed"
    search.stable_error_code = stable
    search.completed_at = now
    search.lease_owner = None
    search.lease_expires_at = None
    job.status = "failed"
    job.stable_error_code = stable
    job.error_detail = "Search stopped with a stable, privacy-safe category."
    job.completed_at = now
    job.lease_owner = None
    job.lease_expires_at = None


async def _audit_search(
    session: AsyncSession,
    search: MyPhotoSearchRunModel,
    outcome: str,
    settings: Settings,
) -> None:
    await record_my_photos_audit(
        session,
        action="my_photos_search_finished",
        agency_id=search.agency_id,
        group_id=search.group_id,
        outcome=outcome,
        gallery_revision=search.gallery_revision,
        configuration_version=settings.my_photos.match_config_version,
    )
