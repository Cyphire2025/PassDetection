"""Storage cleanup execution: focused encrypted tombstone owner."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.logging.logger import get_logger
from app.infrastructure.database.session import AsyncSessionFactory
from app.infrastructure.observability.metrics import metrics
from app.infrastructure.storage.minio_repository import MinioStorageRepository

from .storage_cleanup_cipher import (
    StorageCleanupCipher,
)
from .storage_cleanup_leases import (
    _claim_storage_cleanup_job,
    _complete_storage_cleanup_job,
    _defer_storage_cleanup_job,
)
from .storage_cleanup_policy import (
    MAX_STORAGE_CLEANUP_ATTEMPTS,
    _validated_storage_keys,
)
from .storage_cleanup_types import (
    StorageCleanupClaim,
    StorageCleanupIncompleteError,
    StorageCleanupPayloadError,
    StorageCleanupResult,
)

logger = get_logger("app.infrastructure.documents.storage_cleanup")


async def _execute_storage_cleanup_claim(
    claim: StorageCleanupClaim,
    *,
    session_factory: async_sessionmaker[AsyncSession],
    storage_factory: Callable[[], MinioStorageRepository],
    cipher: StorageCleanupCipher,
) -> StorageCleanupResult:
    try:
        keys = cipher.decrypt(
            claim.ciphertext,
            key_version=claim.encryption_key_version,
        )
        keys = _validated_storage_keys(source=claim.source, storage_keys=keys)
    except StorageCleanupPayloadError as exc:
        await _defer_storage_cleanup_job(
            claim,
            error_code=type(exc).__name__,
            blocked=True,
            session_factory=session_factory,
            now=datetime.now(tz=UTC),
        )
        logger.error(
            "document_storage_cleanup_blocked",
            job_id=str(claim.job_id),
            context_fingerprint=claim.context_fingerprint,
            error_type=type(exc).__name__,
        )
        return StorageCleanupResult(claim.job_id, claim.object_count, 0, False)

    try:
        from app.application.travellers.retention import deletable_storage_keys

        if any(key.startswith("travellers/") for key in keys):
            async with session_factory() as retention_session:
                keys = tuple(
                    await deletable_storage_keys(retention_session, keys, agency_id=claim.agency_id)
                )
        deleted_count = await storage_factory().delete_files(list(keys))
        if deleted_count != len(keys):
            raise StorageCleanupIncompleteError
    except Exception as exc:
        terminal = await _defer_storage_cleanup_job(
            claim,
            error_code=type(exc).__name__,
            blocked=False,
            session_factory=session_factory,
            now=datetime.now(tz=UTC),
        )
        log = logger.error if terminal else logger.warning
        log(
            "document_storage_cleanup_terminal_failure"
            if terminal
            else "document_storage_cleanup_retry_scheduled",
            job_id=str(claim.job_id),
            context_fingerprint=claim.context_fingerprint,
            object_count=claim.object_count,
            attempt=claim.attempts,
            max_attempts=MAX_STORAGE_CLEANUP_ATTEMPTS,
            error_type=type(exc).__name__,
        )
        return StorageCleanupResult(claim.job_id, claim.object_count, 0, False)

    await _complete_storage_cleanup_job(claim, session_factory=session_factory)
    metrics.increment("document_storage_cleanup.completed")
    return StorageCleanupResult(
        claim.job_id,
        claim.object_count,
        deleted_count,
        True,
    )


async def process_storage_cleanup_job(
    job_id: uuid.UUID,
    *,
    session_factory: async_sessionmaker[AsyncSession] = AsyncSessionFactory,
    storage_factory: Callable[[], MinioStorageRepository] = MinioStorageRepository,
    cipher: StorageCleanupCipher | None = None,
) -> StorageCleanupResult | None:
    """Attempt one committed cleanup job; failures remain durably retryable."""

    active_cipher = cipher or StorageCleanupCipher.from_settings()
    claim = await _claim_storage_cleanup_job(
        job_id=job_id,
        session_factory=session_factory,
        now=datetime.now(tz=UTC),
    )
    if claim is None:
        return None
    return await _execute_storage_cleanup_claim(
        claim,
        session_factory=session_factory,
        storage_factory=storage_factory,
        cipher=active_cipher,
    )


async def process_due_storage_cleanup_jobs(
    *,
    limit: int = 50,
    session_factory: async_sessionmaker[AsyncSession] = AsyncSessionFactory,
    storage_factory: Callable[[], MinioStorageRepository] = MinioStorageRepository,
    cipher: StorageCleanupCipher | None = None,
) -> int:
    """Lease and process a bounded number of due tombstones."""

    bounded_limit = max(1, min(limit, 200))
    active_cipher = cipher or StorageCleanupCipher.from_settings()
    completed = 0
    for _ in range(bounded_limit):
        claim = await _claim_storage_cleanup_job(
            job_id=None,
            session_factory=session_factory,
            now=datetime.now(tz=UTC),
        )
        if claim is None:
            break
        result = await _execute_storage_cleanup_claim(
            claim,
            session_factory=session_factory,
            storage_factory=storage_factory,
            cipher=active_cipher,
        )
        completed += int(result.completed)
    return completed


_execute_storage_cleanup_claim.__module__ = "app.infrastructure.documents.storage_cleanup"

process_storage_cleanup_job.__module__ = "app.infrastructure.documents.storage_cleanup"

process_due_storage_cleanup_jobs.__module__ = "app.infrastructure.documents.storage_cleanup"
