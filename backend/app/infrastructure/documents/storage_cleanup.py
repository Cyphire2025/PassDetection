"""Durable, encrypted retry workflow for deleting sensitive document objects."""

from __future__ import annotations

import base64
import hashlib
import json
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import cast

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config.settings import get_settings
from app.core.logging.logger import get_logger
from app.infrastructure.database.models import StorageCleanupJobModel
from app.infrastructure.database.session import AsyncSessionFactory
from app.infrastructure.storage.minio_repository import MinioStorageRepository

logger = get_logger(__name__)

STORAGE_CLEANUP_KEY_VERSION = 1
STORAGE_CLEANUP_LEASE_SECONDS = 300
MAX_STORAGE_CLEANUP_KEYS = 2_000
MAX_STORAGE_CLEANUP_KEY_LENGTH = 512
STORAGE_CLEANUP_SOURCES: dict[str, tuple[str, ...]] = {
    "document_distribution_delete": ("document-distribution/",),
    "document_distribution_abort": ("document-distribution/",),
    "document_distribution_compensation": ("document-distribution/",),
    "document_rename_batch_delete": ("document-rename/",),
    "document_rename_compensation": ("document-rename/",),
    "document_verification_staging": ("document-verification-staging/",),
    "passport_submission_delete": (
        # Legacy deployments stored the four canonical submission images in
        # short top-level namespaces.  They remain ownership-bound because
        # keys are read only from the locked submission/crop rows selected for
        # deletion; accepting these prefixes keeps durable cleanup compatible
        # with retained production data.
        "front/",
        "thumbnail/",
        "back/",
        "photo/",
        "visa-photo/",
        "visa_photo/",
        "drafts/",
        "excel-imports/",
        "passport-bulk/",
        "passport-crops/",
        "passport-edits/",
    ),
}


class StorageCleanupPayloadError(ValueError):
    """Raised when a cleanup tombstone cannot be created or decrypted safely."""


class StorageCleanupIncompleteError(RuntimeError):
    """Raised when storage does not acknowledge every idempotent delete."""


@dataclass(frozen=True, slots=True)
class StorageCleanupClaim:
    job_id: uuid.UUID
    context_fingerprint: str
    ciphertext: bytes
    encryption_key_version: int
    source: str
    object_count: int
    attempts: int


@dataclass(frozen=True, slots=True)
class StorageCleanupResult:
    job_id: uuid.UUID
    object_count: int
    deleted_count: int
    completed: bool


class StorageCleanupCipher:
    """Domain-separated encryption for short-lived storage-key tombstones."""

    def __init__(
        self,
        app_secret_key: str,
        *,
        key_version: int = STORAGE_CLEANUP_KEY_VERSION,
        decryption_keys: Mapping[int, str] | None = None,
    ) -> None:
        if key_version < 1:
            raise StorageCleanupPayloadError("Storage cleanup key version is invalid")
        self._fernets = {key_version: _storage_cleanup_fernet(app_secret_key, key_version)}
        for version, fallback_key in (decryption_keys or {}).items():
            if version < 1:
                raise StorageCleanupPayloadError("Storage cleanup key version is invalid")
            fallback = _storage_cleanup_fernet(fallback_key, version)
            if version == key_version and fallback_key != app_secret_key:
                raise StorageCleanupPayloadError("Storage cleanup keyring conflicts")
            self._fernets[version] = fallback
        self._key_version = key_version

    @classmethod
    def from_settings(cls) -> StorageCleanupCipher:
        settings = get_settings()
        configured_key = _secret_value(settings.storage_cleanup_encryption_key)
        active_key = configured_key or settings.app_secret_key
        fallback_keys: dict[int, str] = {}
        for version, value in settings.storage_cleanup_decryption_keys.items():
            fallback = _secret_value(value)
            if fallback is None:
                raise StorageCleanupPayloadError("Storage cleanup decryption key is invalid")
            fallback_keys[version] = fallback
        return cls(
            active_key,
            key_version=settings.storage_cleanup_encryption_key_version,
            decryption_keys=fallback_keys,
        )

    @property
    def key_version(self) -> int:
        return self._key_version

    def encrypt(self, storage_keys: Sequence[str]) -> bytes:
        payload = json.dumps(list(storage_keys), ensure_ascii=False, separators=(",", ":"))
        return cast(bytes, self._fernets[self._key_version].encrypt(payload.encode("utf-8")))

    def decrypt(self, ciphertext: bytes, *, key_version: int) -> tuple[str, ...]:
        fernet = self._fernets.get(key_version)
        if fernet is None:
            raise StorageCleanupPayloadError("Storage cleanup key version is unavailable")
        try:
            plaintext = fernet.decrypt(ciphertext)
            payload = json.loads(plaintext.decode("utf-8"))
        except (InvalidToken, UnicodeDecodeError, json.JSONDecodeError):
            raise StorageCleanupPayloadError("Storage cleanup payload is invalid") from None
        if not isinstance(payload, list) or not all(isinstance(item, str) for item in payload):
            raise StorageCleanupPayloadError("Storage cleanup payload is invalid")
        return tuple(payload)


def _secret_value(value: object) -> str | None:
    if value is None:
        return None
    getter = getattr(value, "get_secret_value", None)
    if callable(getter):
        secret = getter()
        return secret if isinstance(secret, str) else None
    return value if isinstance(value, str) else None


def _storage_cleanup_fernet(secret: str, key_version: int) -> Fernet:
    if not isinstance(secret, str) or len(secret) < 16:
        raise StorageCleanupPayloadError("Storage cleanup encryption is unavailable")
    derived = hashlib.sha256(
        b"passdetection-storage-cleanup\x00"
        + str(key_version).encode("ascii")
        + b"\x00"
        + secret.encode("utf-8")
    ).digest()
    return Fernet(base64.urlsafe_b64encode(derived))


def _validated_storage_keys(
    *,
    source: str,
    storage_keys: Sequence[str],
    max_keys: int | None = MAX_STORAGE_CLEANUP_KEYS,
) -> tuple[str, ...]:
    allowed_prefixes = STORAGE_CLEANUP_SOURCES.get(source)
    if allowed_prefixes is None:
        raise StorageCleanupPayloadError("Unsupported storage cleanup source")
    keys = tuple(dict.fromkeys(storage_keys))
    if not keys or (max_keys is not None and len(keys) > max_keys):
        raise StorageCleanupPayloadError("Storage cleanup object count is invalid")
    if any(
        not key
        or len(key) > MAX_STORAGE_CLEANUP_KEY_LENGTH
        or "\x00" in key
        or not key.startswith(allowed_prefixes)
        for key in keys
    ):
        raise StorageCleanupPayloadError("Storage cleanup object scope is invalid")
    return keys


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
                await session.delete(job)


async def _defer_storage_cleanup_job(
    claim: StorageCleanupClaim,
    *,
    error_code: str,
    blocked: bool,
    session_factory: async_sessionmaker[AsyncSession],
    now: datetime,
) -> None:
    async with session_factory() as session:
        async with session.begin():
            result = await session.execute(
                select(StorageCleanupJobModel)
                .where(StorageCleanupJobModel.id == claim.job_id)
                .with_for_update()
            )
            job = result.scalar_one_or_none()
            if job is None:
                return
            job.status = "blocked" if blocked else "pending"
            backoff_seconds = min(21_600, 15 * (2 ** min(claim.attempts, 10)))
            job.next_attempt_at = now + timedelta(seconds=backoff_seconds)
            job.lease_expires_at = None
            job.last_error_code = error_code[:120]
            job.updated_at = now


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
        deleted_count = await storage_factory().delete_files(list(keys))
        if deleted_count != len(keys):
            raise StorageCleanupIncompleteError
    except Exception as exc:
        await _defer_storage_cleanup_job(
            claim,
            error_code=type(exc).__name__,
            blocked=False,
            session_factory=session_factory,
            now=datetime.now(tz=UTC),
        )
        logger.warning(
            "document_storage_cleanup_retry_scheduled",
            job_id=str(claim.job_id),
            context_fingerprint=claim.context_fingerprint,
            object_count=claim.object_count,
            attempt=claim.attempts,
            error_type=type(exc).__name__,
        )
        return StorageCleanupResult(claim.job_id, claim.object_count, 0, False)

    await _complete_storage_cleanup_job(claim, session_factory=session_factory)
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
