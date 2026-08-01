"""Bounded reconciliation for travel-document objects without database owners."""

from __future__ import annotations

import base64
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from redis.asyncio import Redis
from sqlalchemy import select

from app.core.config.settings import get_settings
from app.core.logging.logger import get_logger
from app.infrastructure.database.models import (
    DistributedDocumentModel,
    DocumentRenameItemModel,
)
from app.infrastructure.database.session import AsyncSessionFactory
from app.infrastructure.documents.storage_cleanup import StorageCleanupCipher
from app.infrastructure.storage.minio_repository import MinioStorageRepository

logger = get_logger(__name__)

DOCUMENT_ORPHAN_GRACE = timedelta(hours=24)
DOCUMENT_ORPHAN_PAGE_SIZE = 2_000
DOCUMENT_ORPHAN_DELETE_BATCH_SIZE = 250
DOCUMENT_ORPHAN_CURSOR_TTL_SECONDS = 7 * 24 * 60 * 60
DOCUMENT_ORPHAN_PREFIXES = (
    "document-rename/",
    "document-distribution/",
)

ReferenceLookup = Callable[[str, Sequence[str]], Awaitable[set[str]]]


@dataclass(frozen=True, slots=True)
class DocumentOrphanReconciliationResult:
    scanned_count: int
    stale_candidate_count: int
    deleted_count: int


async def _database_referenced_keys(prefix: str, keys: Sequence[str]) -> set[str]:
    if not keys:
        return set()
    if prefix == "document-rename/":
        column = DocumentRenameItemModel.storage_key
    elif prefix == "document-distribution/":
        column = DistributedDocumentModel.storage_key
    else:  # pragma: no cover - fixed internal callers only
        raise ValueError("Unsupported travel-document storage prefix")

    referenced: set[str] = set()
    async with AsyncSessionFactory() as session:
        for offset in range(0, len(keys), 1_000):
            result = await session.execute(
                select(column).where(column.in_(keys[offset : offset + 1_000]))
            )
            referenced.update(value for value in result.scalars().all() if value)
    return referenced


def _cursor_key(prefix: str) -> str:
    namespace = prefix.rstrip("/").replace("/", ":")
    return f"passdetection:document-orphans:cursor:{namespace}"


async def _read_cursor(
    client: Any,
    prefix: str,
    *,
    cipher: StorageCleanupCipher,
) -> str | None:
    try:
        value = await client.get(_cursor_key(prefix))
    except Exception as exc:
        logger.warning(
            "document_orphan_cursor_read_failed",
            prefix=prefix,
            error_type=type(exc).__name__,
        )
        return None
    if isinstance(value, bytes):
        value = value.decode("ascii", errors="ignore")
    try:
        version_text, encoded = value.split(":", 1) if isinstance(value, str) else ("", "")
        decrypted = cipher.decrypt(
            base64.urlsafe_b64decode(encoded.encode("ascii")),
            key_version=int(version_text),
        )
    except Exception:
        return None
    cursor = decrypted[0] if len(decrypted) == 1 else None
    return cursor if cursor is not None and cursor.startswith(prefix) else None


async def _advance_cursor(
    client: Any,
    *,
    prefix: str,
    objects: Sequence[tuple[str, datetime | None]],
    cipher: StorageCleanupCipher,
) -> None:
    try:
        if len(objects) < DOCUMENT_ORPHAN_PAGE_SIZE:
            await client.delete(_cursor_key(prefix))
            return
        encrypted = cipher.encrypt([objects[-1][0]])
        cursor_value = (
            f"{cipher.key_version}:"
            + base64.urlsafe_b64encode(encrypted).decode("ascii")
        )
        await client.setex(
            _cursor_key(prefix),
            DOCUMENT_ORPHAN_CURSOR_TTL_SECONDS,
            cursor_value,
        )
    except Exception as exc:
        # Cursor loss only causes a safe repeated scan; it must never turn an
        # otherwise successful cleanup into a failed Celery task.
        logger.warning(
            "document_orphan_cursor_write_failed",
            prefix=prefix,
            error_type=type(exc).__name__,
        )


def _is_past_grace(modified_at: datetime | None, *, cutoff: datetime) -> bool:
    if modified_at is None:
        return False
    normalized = (
        modified_at.replace(tzinfo=UTC)
        if modified_at.tzinfo is None
        else modified_at.astimezone(UTC)
    )
    return normalized <= cutoff


async def reconcile_document_storage_orphans(
    *,
    storage: MinioStorageRepository | None = None,
    reference_lookup: ReferenceLookup = _database_referenced_keys,
    cursor_client: Any | None = None,
    cursor_cipher: StorageCleanupCipher | None = None,
    now: datetime | None = None,
) -> DocumentOrphanReconciliationResult:
    """Delete only old, unreferenced objects from fixed internal namespaces.

    The 24-hour grace covers lost COMMIT acknowledgements and in-flight
    retries. A Redis cursor rotates bounded pages so large active namespaces do
    not permanently hide later orphaned keys.
    """

    active_storage = storage or MinioStorageRepository()
    owned_cursor = cursor_client is None
    cursor = cursor_client or Redis.from_url(
        get_settings().redis.url,
        encoding="utf-8",
        decode_responses=True,
        socket_connect_timeout=1.0,
        socket_timeout=1.0,
    )
    cipher = cursor_cipher or StorageCleanupCipher.from_settings()
    cutoff = (now or datetime.now(tz=UTC)) - DOCUMENT_ORPHAN_GRACE
    scanned_count = 0
    stale_candidate_count = 0
    deleted_count = 0

    try:
        for prefix in DOCUMENT_ORPHAN_PREFIXES:
            start_after = await _read_cursor(cursor, prefix, cipher=cipher)
            objects = await active_storage.list_files(
                prefix=prefix,
                limit=DOCUMENT_ORPHAN_PAGE_SIZE,
                start_after=start_after,
            )
            scanned_count += len(objects)
            stale_keys = [
                key
                for key, modified_at in objects
                if _is_past_grace(modified_at, cutoff=cutoff)
            ]
            stale_candidate_count += len(stale_keys)
            referenced = await reference_lookup(prefix, stale_keys)
            orphaned = [key for key in stale_keys if key not in referenced]
            for offset in range(0, len(orphaned), DOCUMENT_ORPHAN_DELETE_BATCH_SIZE):
                deleted_count += await active_storage.delete_files(
                    orphaned[offset : offset + DOCUMENT_ORPHAN_DELETE_BATCH_SIZE]
                )
            await _advance_cursor(
                cursor,
                prefix=prefix,
                objects=objects,
                cipher=cipher,
            )
    finally:
        if owned_cursor:
            close = getattr(cursor, "aclose", None)
            if callable(close):
                await close()

    return DocumentOrphanReconciliationResult(
        scanned_count=scanned_count,
        stale_candidate_count=stale_candidate_count,
        deleted_count=deleted_count,
    )
