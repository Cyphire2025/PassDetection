"""Bounded, age-gated reconciliation of unreferenced email-owned objects."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.core.config.settings import get_settings
from app.infrastructure.database.email_models import EmailArtifactModel
from app.infrastructure.database.models import DistributedDocumentModel
from app.infrastructure.database.session import AsyncSessionFactory
from app.infrastructure.storage.minio_repository import MinioStorageRepository

_EMAIL_STORAGE_PREFIXES = (
    "email-integrations/",
    "email-integrations-canonical/",
)
_EMAIL_STORAGE_RECONCILE_PAGE_SIZE = 1_000


async def _reconcile_orphaned_email_storage(
    *,
    storage: MinioStorageRepository,
    now: datetime,
) -> int:
    """Delete aged email-owned objects with no durable database reference."""

    settings = get_settings()
    cutoff = now - timedelta(hours=settings.email_storage_orphan_grace_hours)
    deleted_count = 0
    for prefix in _EMAIL_STORAGE_PREFIXES:
        start_after: str | None = None
        while True:
            objects = await storage.list_files(
                prefix=prefix,
                limit=_EMAIL_STORAGE_RECONCILE_PAGE_SIZE,
                start_after=start_after,
            )
            if not objects:
                break
            candidate_keys = list(
                dict.fromkeys(
                    key
                    for key, modified_at in objects
                    if _storage_object_is_older_than(modified_at, cutoff=cutoff)
                )
            )
            if candidate_keys:
                deleted_count += await _delete_unreferenced_email_storage_keys(
                    storage=storage,
                    candidate_keys=candidate_keys,
                )
            next_start_after = objects[-1][0]
            if len(objects) < _EMAIL_STORAGE_RECONCILE_PAGE_SIZE or next_start_after == start_after:
                break
            start_after = next_start_after
    return deleted_count


async def _delete_unreferenced_email_storage_keys(
    *,
    storage: MinioStorageRepository,
    candidate_keys: list[str],
) -> int:
    if not candidate_keys:
        return 0

    async with AsyncSessionFactory() as session:
        artifact_keys = set(
            (
                await session.execute(
                    select(EmailArtifactModel.storage_key).where(
                        EmailArtifactModel.storage_key.in_(candidate_keys)
                    )
                )
            )
            .scalars()
            .all()
        )
        document_keys = set(
            (
                await session.execute(
                    select(DistributedDocumentModel.storage_key).where(
                        DistributedDocumentModel.storage_key.in_(candidate_keys)
                    )
                )
            )
            .scalars()
            .all()
        )
    referenced_keys = artifact_keys | document_keys
    orphaned_keys = [key for key in candidate_keys if key not in referenced_keys]
    if not orphaned_keys:
        return 0
    return await storage.delete_files(orphaned_keys)


def _storage_object_is_older_than(
    modified_at: datetime | None,
    *,
    cutoff: datetime,
) -> bool:
    if modified_at is None:
        return False
    normalized = modified_at if modified_at.tzinfo is not None else modified_at.replace(tzinfo=UTC)
    return normalized <= cutoff


# Preserve legacy function exports while the implementation has an explicit owner.
_reconcile_orphaned_email_storage.__module__ = "app.infrastructure.email.tasks"
_delete_unreferenced_email_storage_keys.__module__ = "app.infrastructure.email.tasks"
_storage_object_is_older_than.__module__ = "app.infrastructure.email.tasks"
