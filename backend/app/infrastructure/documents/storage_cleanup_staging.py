"""Storage cleanup staging: focused encrypted tombstone owner."""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.infrastructure.database.models import StorageCleanupJobModel
from app.infrastructure.database.session import AsyncSessionFactory

from .storage_cleanup_cipher import (
    StorageCleanupCipher,
)
from .storage_cleanup_policy import (
    MAX_STORAGE_CLEANUP_KEYS,
    _validated_storage_keys,
)


def _stage_validated_storage_cleanup_job(
    session: AsyncSession,
    *,
    agency_id: uuid.UUID | None,
    source: str,
    context_id: str,
    keys: tuple[str, ...],
    cipher: StorageCleanupCipher,
    timestamp: datetime,
    not_before: datetime | None = None,
) -> StorageCleanupJobModel:
    context_fingerprint = hashlib.sha256(f"{source}:{context_id}".encode("utf-8")).hexdigest()
    job = StorageCleanupJobModel(
        id=uuid.uuid4(),
        agency_id=agency_id,
        source=source,
        context_fingerprint=context_fingerprint,
        storage_keys_ciphertext=cipher.encrypt(keys),
        encryption_key_version=cipher.key_version,
        object_count=len(keys),
        status="pending",
        attempts=0,
        next_attempt_at=not_before or timestamp,
        lease_expires_at=None,
        last_error_code=None,
        created_at=timestamp,
        updated_at=timestamp,
    )
    session.add(job)
    return job


def stage_storage_cleanup_job(
    session: AsyncSession,
    *,
    agency_id: uuid.UUID | None,
    source: str,
    context_id: str,
    storage_keys: Sequence[str],
    cipher: StorageCleanupCipher | None = None,
    now: datetime | None = None,
    not_before: datetime | None = None,
) -> StorageCleanupJobModel | None:
    """Stage a tombstone in the same transaction as authoritative DB deletion."""

    unique_keys = tuple(dict.fromkeys(key for key in storage_keys if key))
    if not unique_keys:
        return None
    keys = _validated_storage_keys(source=source, storage_keys=unique_keys)
    return _stage_validated_storage_cleanup_job(
        session,
        agency_id=agency_id,
        source=source,
        context_id=context_id,
        keys=keys,
        cipher=cipher or StorageCleanupCipher.from_settings(),
        timestamp=now or datetime.now(tz=UTC),
        not_before=not_before,
    )


def stage_storage_cleanup_jobs(
    session: AsyncSession,
    *,
    agency_id: uuid.UUID | None,
    source: str,
    context_id: str,
    storage_keys: Sequence[str],
    cipher: StorageCleanupCipher | None = None,
    now: datetime | None = None,
    not_before: datetime | None = None,
) -> tuple[StorageCleanupJobModel, ...]:
    """Stage deterministic, bounded tombstone chunks in the owning transaction."""

    unique_keys = tuple(sorted(dict.fromkeys(key for key in storage_keys if key)))
    if not unique_keys:
        return ()

    # Validate the complete input before adding any job to the session.  The
    # per-job limit is an encrypted-payload bound, not a bulk-delete limit.
    keys = _validated_storage_keys(source=source, storage_keys=unique_keys, max_keys=None)
    active_cipher = cipher or StorageCleanupCipher.from_settings()
    timestamp = now or datetime.now(tz=UTC)
    chunk_count = (len(keys) + MAX_STORAGE_CLEANUP_KEYS - 1) // MAX_STORAGE_CLEANUP_KEYS
    jobs: list[StorageCleanupJobModel] = []
    for chunk_index in range(chunk_count):
        start = chunk_index * MAX_STORAGE_CLEANUP_KEYS
        chunk = keys[start : start + MAX_STORAGE_CLEANUP_KEYS]
        chunk_context = (
            context_id
            if chunk_count == 1
            else f"{context_id}:chunk:{chunk_index + 1}:{chunk_count}"
        )
        jobs.append(
            _stage_validated_storage_cleanup_job(
                session,
                agency_id=agency_id,
                source=source,
                context_id=chunk_context,
                keys=chunk,
                cipher=active_cipher,
                timestamp=timestamp,
                not_before=not_before,
            )
        )
    return tuple(jobs)


async def persist_storage_cleanup_job(
    *,
    agency_id: uuid.UUID | None,
    source: str,
    context_id: str,
    storage_keys: Sequence[str],
    session_factory: async_sessionmaker[AsyncSession] = AsyncSessionFactory,
    cipher: StorageCleanupCipher | None = None,
    not_before: datetime | None = None,
) -> uuid.UUID | None:
    """Commit a compensation tombstone after the owning transaction rolled back."""

    async with session_factory() as session:
        async with session.begin():
            job = stage_storage_cleanup_job(
                session,
                agency_id=agency_id,
                source=source,
                context_id=context_id,
                storage_keys=storage_keys,
                cipher=cipher,
                not_before=not_before,
            )
            return job.id if job is not None else None


_stage_validated_storage_cleanup_job.__module__ = "app.infrastructure.documents.storage_cleanup"

stage_storage_cleanup_job.__module__ = "app.infrastructure.documents.storage_cleanup"

stage_storage_cleanup_jobs.__module__ = "app.infrastructure.documents.storage_cleanup"

persist_storage_cleanup_job.__module__ = "app.infrastructure.documents.storage_cleanup"
