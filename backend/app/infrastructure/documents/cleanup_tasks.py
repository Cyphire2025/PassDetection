"""Celery entry point for durable document object-storage cleanup."""

from __future__ import annotations

from typing import cast

from celery.utils.log import get_task_logger

from app.infrastructure.celery_async_runtime import celery_async_runtime
from app.infrastructure.documents.storage_cleanup import (
    process_due_storage_cleanup_jobs,
)
from app.infrastructure.processing.celery_app import celery_app

logger = get_task_logger(__name__)


@celery_app.task(  # type: ignore[untyped-decorator]
    name="documents.cleanup_storage",
    queue="passport_ocr",
)
def cleanup_document_storage() -> int:
    """Retry a bounded lease-safe page of committed cleanup tombstones."""

    try:
        return cast(int, celery_async_runtime.run(process_due_storage_cleanup_jobs()))
    except Exception as exc:
        logger.error(
            "document_storage_cleanup_task_failed error_type=%s",
            type(exc).__name__,
        )
        raise
