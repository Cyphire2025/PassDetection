"""Storage cleanup leases: focused encrypted tombstone owner."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.infrastructure.database.models import AuditLogModel, StorageCleanupJobModel
from app.infrastructure.observability.metrics import metrics

from .storage_cleanup_policy import (
    MAX_STORAGE_CLEANUP_ATTEMPTS,
    STORAGE_CLEANUP_LEASE_SECONDS,
)
from .storage_cleanup_types import (
    StorageCleanupClaim,
)


async def _claim_storage_cleanup_job(
    *,
    job_id: uuid.UUID | None,
    session_factory: async_sessionmaker[AsyncSession],
    now: datetime,
) -> StorageCleanupClaim | None:
    async with session_factory() as session:
        async with session.begin():
            due = or_(
                and_(
                    StorageCleanupJobModel.status == "pending",
                    StorageCleanupJobModel.next_attempt_at <= now,
                ),
                and_(
                    StorageCleanupJobModel.status == "running",
                    StorageCleanupJobModel.lease_expires_at.is_not(None),
                    StorageCleanupJobModel.lease_expires_at <= now,
                ),
            )
            statement = (
                select(StorageCleanupJobModel)
                .where(due)
                .order_by(
                    StorageCleanupJobModel.next_attempt_at,
                    StorageCleanupJobModel.created_at,
                    StorageCleanupJobModel.id,
                )
                .limit(1)
                .with_for_update(skip_locked=True)
                .execution_options(populate_existing=True)
            )
            if job_id is not None:
                statement = statement.where(StorageCleanupJobModel.id == job_id)
            result = await session.execute(statement)
            job = result.scalar_one_or_none()
            if job is None:
                return None
            job.status = "running"
            job.attempts += 1
            job.lease_expires_at = now + timedelta(seconds=STORAGE_CLEANUP_LEASE_SECONDS)
            job.updated_at = now
            return StorageCleanupClaim(
                job_id=job.id,
                context_fingerprint=job.context_fingerprint,
                ciphertext=bytes(job.storage_keys_ciphertext),
                encryption_key_version=job.encryption_key_version,
                source=job.source,
                object_count=job.object_count,
                attempts=job.attempts,
                agency_id=getattr(job, "agency_id", None),
            )


async def _complete_storage_cleanup_job(
    claim: StorageCleanupClaim,
    *,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        async with session.begin():
            result = await session.execute(
                select(StorageCleanupJobModel)
                .where(StorageCleanupJobModel.id == claim.job_id)
                .with_for_update()
            )
            job = result.scalar_one_or_none()
            if job is not None:
                completed_at = datetime.now(tz=UTC)
                session.add(
                    AuditLogModel(
                        id=uuid.uuid4(),
                        agency_id=claim.agency_id,
                        user_id=None,
                        actor_email=None,
                        action="document_storage_cleanup_completed",
                        entity_type="storage_cleanup_job",
                        entity_id=str(claim.job_id),
                        metadata_json={
                            "source": claim.source,
                            "context_fingerprint": claim.context_fingerprint,
                            "object_count": claim.object_count,
                            "attempts": claim.attempts,
                        },
                        created_at=completed_at,
                    )
                )
                await session.delete(job)


async def _defer_storage_cleanup_job(
    claim: StorageCleanupClaim,
    *,
    error_code: str,
    blocked: bool,
    session_factory: async_sessionmaker[AsyncSession],
    now: datetime,
) -> bool:
    terminal = blocked or claim.attempts >= MAX_STORAGE_CLEANUP_ATTEMPTS
    async with session_factory() as session:
        async with session.begin():
            result = await session.execute(
                select(StorageCleanupJobModel)
                .where(StorageCleanupJobModel.id == claim.job_id)
                .with_for_update()
            )
            job = result.scalar_one_or_none()
            if job is None:
                return terminal
            job.status = "blocked" if terminal else "pending"
            backoff_seconds = min(21_600, 15 * (2 ** min(claim.attempts, 10)))
            job.next_attempt_at = now + timedelta(seconds=backoff_seconds)
            job.lease_expires_at = None
            job.last_error_code = error_code[:120]
            job.updated_at = now
            if terminal:
                session.add(
                    AuditLogModel(
                        id=uuid.uuid4(),
                        agency_id=claim.agency_id,
                        user_id=None,
                        actor_email=None,
                        action="document_storage_cleanup_terminal_failure",
                        entity_type="storage_cleanup_job",
                        entity_id=str(claim.job_id),
                        result="failed",
                        metadata_json={
                            "source": claim.source,
                            "context_fingerprint": claim.context_fingerprint,
                            "object_count": claim.object_count,
                            "attempts": claim.attempts,
                            "error_code": error_code[:120],
                        },
                        created_at=now,
                    )
                )
    metric_name = (
        "document_storage_cleanup.terminal_failures"
        if terminal
        else "document_storage_cleanup.retries_scheduled"
    )
    metrics.increment(metric_name)
    return terminal


_claim_storage_cleanup_job.__module__ = "app.infrastructure.documents.storage_cleanup"

_complete_storage_cleanup_job.__module__ = "app.infrastructure.documents.storage_cleanup"

_defer_storage_cleanup_job.__module__ = "app.infrastructure.documents.storage_cleanup"
