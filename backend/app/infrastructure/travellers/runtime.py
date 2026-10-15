"""Bounded periodic consumers for durable traveller jobs and deletion intents."""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from time import monotonic

from sqlalchemy import or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.travellers.company_history_jobs import advance_company_history_chain
from app.application.travellers.incremental_history import DIRTY
from app.application.travellers.reconciliation import reconcile_page
from app.application.travellers.snapshot_access import live_trip_asset_reference
from app.core.config.traveller_reuse import get_traveller_reuse_settings
from app.core.logging.logger import get_logger
from app.infrastructure.database.session import AsyncSessionFactory
from app.infrastructure.database.traveller_reuse_models import (
    TravellerDocumentAssetModel,
    TravellerProfileModel,
    TravellerReconciliationJobModel,
)
from app.infrastructure.documents.storage_cleanup import stage_storage_cleanup_jobs
from app.infrastructure.observability.metrics import metrics
from app.infrastructure.security.traveller_reuse_crypto import (
    ReuseCryptoUnavailable,
    TravellerReuseCrypto,
)
from app.infrastructure.travellers.asset_copy import copy_next_asset

MAX_RECONCILIATION_PAGES = 40
RECONCILIATION_BURST_SECONDS = 50
logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class ReconciliationClaim:
    job_id: uuid.UUID
    lease_expires_at: datetime
    attempt_count: int


async def _reserve_reconciliation(factory: async_sessionmaker[AsyncSession]) -> ReconciliationClaim | None:
    now = datetime.now(UTC)
    async with factory() as session, session.begin():
        row = await session.scalar(select(TravellerReconciliationJobModel).where(
            TravellerReconciliationJobModel.status.in_(("queued", "running")),
            TravellerReconciliationJobModel.available_at <= now,
            or_(TravellerReconciliationJobModel.lease_expires_at.is_(None),
                TravellerReconciliationJobModel.lease_expires_at <= now),
        ).order_by(TravellerReconciliationJobModel.available_at, TravellerReconciliationJobModel.id)
            .limit(1).with_for_update(skip_locked=True))
        if row is None:
            return None
        if row.attempt_count >= 5:
            row.status, row.last_error_code = "failed", "attempts_exhausted"
            row.completed_at = now
            return None
        row.attempt_count += 1
        row.status = "running"
        row.lease_expires_at = now + timedelta(seconds=60)
        row.available_at = row.lease_expires_at
        return ReconciliationClaim(row.id, row.lease_expires_at, row.attempt_count)


async def run_reconciliation_tick(
    *, session_factory: async_sessionmaker[AsyncSession] = AsyncSessionFactory,
    crypto: TravellerReuseCrypto | None = None,
) -> int:
    try:
        crypto = crypto or TravellerReuseCrypto(get_traveller_reuse_settings())
    except ReuseCryptoUnavailable:
        metrics.increment("traveller.reconciliation.configuration_unavailable")
        return 0
    processed, deadline = 0, monotonic() + RECONCILIATION_BURST_SECONDS
    for _ in range(MAX_RECONCILIATION_PAGES // 2):
        if monotonic() >= deadline:
            break
        try:
            async with asyncio.timeout(max(0.01, min(30, deadline - monotonic()))):
                async with session_factory() as session, session.begin():
                    await advance_company_history_chain(session)
        except TimeoutError:
            break
        if monotonic() >= deadline:
            break
        try:
            # Include connection admission and lease reservation in the burst
            # deadline. Cancellation rolls back the page; its lease retries.
            async with asyncio.timeout(max(0.01, deadline - monotonic())):
                # Each worker process has one DB connection. Parallelism comes
                # from workers, bounded globally by the two advisory slots.
                results = [await _reconciliation_slot(session_factory, crypto, slot, deadline) for slot in range(2)]
        except TimeoutError:
            break
        processed += sum(count for count, _attempted in results)
        if not any(attempted for _count, attempted in results):
            break
    metrics.increment("traveller.reconciliation.processed", processed)
    return processed


async def _reconciliation_slot(factory: async_sessionmaker[AsyncSession], crypto: TravellerReuseCrypto,
    slot: int, deadline: float,
) -> tuple[int, bool]:
    if monotonic() >= deadline:
        return 0, False
    # Commit the crash-recovery lease before processing. Admission and page work
    # then share ONE connection; workers intentionally have a one-connection pool.
    claim = await _reserve_reconciliation(factory)
    if claim is None:
        return 0, False
    admitted = False
    try:
        async with asyncio.timeout(max(0.01, min(30, deadline - monotonic()))):
            async with factory() as session, session.begin():
                admitted = session.bind is None or session.bind.dialect.name != "postgresql" or bool(
                    await session.scalar(text("SELECT pg_try_advisory_xact_lock(913702, :slot)"), {"slot": slot}))
                if admitted:
                    page = await reconcile_page(session, job_id=claim.job_id, crypto=crypto)
                    job = await session.get(TravellerReconciliationJobModel, claim.job_id)
                    if job is not None and job.status == "queued":
                        job.available_at = datetime.now(UTC)
        if admitted:
            metrics.increment("traveller.reconciliation.pages")
            return page.processed if page is not None else 0, True
        await _release_reconciliation(factory, claim)
        return 0, False
    except Exception as exc:
        sqlstate = getattr(getattr(exc, "orig", None), "sqlstate", None)
        if not isinstance(sqlstate, str) or len(sqlstate) != 5 or not sqlstate.isascii() or not sqlstate.isalnum():
            sqlstate = None
        logger.warning("traveller_reconciliation_page_failed", job_id=str(claim.job_id),
            error_type=type(exc).__name__, sqlstate=sqlstate)
        # The page has released its connection before this short failure write.
        # If even this times out, the bounded durable lease recovers.
        try:
            async with asyncio.timeout(5):
                await _fail_reconciliation(factory, claim)
        except TimeoutError:
            pass
        metrics.increment("traveller.reconciliation.failures")
        return 0, True


async def _claimed_job(session: AsyncSession, claim: ReconciliationClaim) -> TravellerReconciliationJobModel | None:
    job: TravellerReconciliationJobModel | None = await session.scalar(select(TravellerReconciliationJobModel).where(
        TravellerReconciliationJobModel.id == claim.job_id,
        TravellerReconciliationJobModel.status == "running",
        TravellerReconciliationJobModel.lease_expires_at == claim.lease_expires_at,
        TravellerReconciliationJobModel.attempt_count == claim.attempt_count).with_for_update())
    return job


async def _release_reconciliation(factory: async_sessionmaker[AsyncSession], claim: ReconciliationClaim) -> None:
    """Busy global slots are backpressure, not a failed processing attempt."""
    async with factory() as session, session.begin():
        job = await _claimed_job(session, claim)
        if job is not None:
            job.status, job.lease_expires_at = "queued", None
            job.attempt_count -= 1
            job.available_at = datetime.now(UTC) + timedelta(seconds=1)


async def _fail_reconciliation(factory: async_sessionmaker[AsyncSession], claim: ReconciliationClaim) -> None:
    async with factory() as session, session.begin():
        job = await _claimed_job(session, claim)
        if job is not None:
            job.status = "failed" if job.attempt_count >= 5 else "queued"
            if job.last_error_code != DIRTY:
                job.last_error_code = "page_processing_failed"
            job.available_at = datetime.now(UTC) + timedelta(seconds=min(300, 5 * 2 ** job.attempt_count))
            job.lease_expires_at = None


async def run_asset_copy_tick() -> int:
    copied = 0
    # Drain bounded bursts while capacity exists; a fixed two-file/30s cadence
    # would make large authorized imports unnecessarily slow.
    async with asyncio.timeout(50):
        for _ in range(20):
            results = await asyncio.gather(copy_next_asset(), copy_next_asset())
            copied += sum(results)
            if not any(results):
                break
    return copied


async def stage_withdrawn_asset_deletions(
    *, session_factory: async_sessionmaker[AsyncSession] = AsyncSessionFactory,
) -> int:
    """At most 100 assets per tick; future ticks continue without a full scan."""
    async with session_factory() as session, session.begin():
        assets = list((await session.scalars(select(TravellerDocumentAssetModel).join(
            TravellerProfileModel, TravellerProfileModel.id == TravellerDocumentAssetModel.traveller_id,
        ).where(or_(TravellerProfileModel.reuse_permission_status == "withdrawn",
                    TravellerProfileModel.status == "deleted", TravellerProfileModel.deleted_at.is_not(None)),
                TravellerDocumentAssetModel.availability != "purged",
                or_(TravellerProfileModel.status == "deleted", TravellerProfileModel.deleted_at.is_not(None),
                    ~live_trip_asset_reference()))
            .order_by(TravellerDocumentAssetModel.id).limit(100)
            .with_for_update(skip_locked=True, of=TravellerDocumentAssetModel))).all())
        for asset in assets:
            asset.availability, asset.purged_at = "purged", datetime.now(UTC)
            if asset.object_key:
                stage_storage_cleanup_jobs(session, agency_id=asset.agency_id,
                    source="traveller_profile_withdrawal", context_id=str(asset.id), storage_keys=[asset.object_key],
                    not_before=asset.lease_expires_at)
        return len(assets)
