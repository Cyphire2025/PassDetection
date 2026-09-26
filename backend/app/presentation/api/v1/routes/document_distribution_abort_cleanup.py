"""Attempt durable storage cleanup after the upload abort commits."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable, Sequence

from app.infrastructure.database.models import StorageCleanupJobModel
from app.infrastructure.documents.storage_cleanup import StorageCleanupResult
from app.presentation.api.v1.routes.document_distribution_shared import logger


async def complete_abort_storage_cleanup(
    cleanup_jobs: Sequence[StorageCleanupJobModel], *, batch_id: uuid.UUID,
    group_id: uuid.UUID, document_type: str,
    process_job: Callable[[uuid.UUID], Awaitable[StorageCleanupResult | None]],
) -> bool:
    storage_cleanup_pending = False
    for cleanup_job in cleanup_jobs:
        try:
            cleanup_result = await process_job(cleanup_job.id)
            if cleanup_result is None or not cleanup_result.completed:
                storage_cleanup_pending = True
        except Exception as exc:
            storage_cleanup_pending = True
            logger.warning(
                "document_distribution_abort_cleanup_deferred",
                batch_id=str(batch_id),
                group_id=str(group_id),
                document_type=document_type,
                cleanup_job_id=str(cleanup_job.id),
                object_count=cleanup_job.object_count,
                error_type=type(exc).__name__,
            )

    return storage_cleanup_pending
