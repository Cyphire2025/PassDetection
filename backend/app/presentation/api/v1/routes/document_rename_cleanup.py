"""Owned document-rename object compensation and durable fallback."""

from __future__ import annotations

import uuid

from app.core.logging.logger import get_logger
from app.infrastructure.documents.storage_cleanup import (
    persist_storage_cleanup_job,
)
from app.infrastructure.storage.minio_repository import MinioStorageRepository

logger = get_logger("app.presentation.api.v1.routes.document_rename")


async def _cleanup_owned_rename_storage(
    storage: MinioStorageRepository,
    storage_keys: list[str],
    *,
    agency_id: uuid.UUID,
    batch_id: uuid.UUID,
) -> None:
    if not storage_keys:
        return
    try:
        await storage.delete_files(storage_keys)
    except Exception:
        logger.warning(
            "document_rename_storage_cleanup_deferred",
            object_count=len(storage_keys),
        )
        try:
            await persist_storage_cleanup_job(
                agency_id=agency_id,
                source="document_rename_compensation",
                context_id=str(batch_id),
                storage_keys=storage_keys,
            )
        except Exception as exc:
            logger.error(
                "document_rename_cleanup_tracking_failed",
                batch_id=str(batch_id),
                object_count=len(storage_keys),
                error_type=type(exc).__name__,
            )
