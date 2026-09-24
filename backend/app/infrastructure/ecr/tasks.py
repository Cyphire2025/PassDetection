"""Celery entry points for durable ECR batches and recovery."""

from __future__ import annotations

import uuid
from typing import Any

from app.infrastructure.celery_async_runtime import celery_async_runtime
from app.infrastructure.ecr import ECR_BATCH_TASK, ECR_QUEUE, ECR_RECOVERY_TASK, ECR_RETENTION_TASK
from app.infrastructure.ecr.runtime import apply_retention, process_batch, recover_batches
from app.infrastructure.processing.celery_app import celery_app


@celery_app.task(
    bind=True,
    name=ECR_BATCH_TASK,
    queue=ECR_QUEUE,
    max_retries=5,
    soft_time_limit=59 * 60,
    time_limit=60 * 60,
)  # type: ignore[untyped-decorator]
def process_ecr_batch(self: Any, batch_id: str) -> str:
    """Process one bounded drain; continuation is a new task at the queue tail."""
    try:
        parsed_id = uuid.UUID(batch_id)
    except (TypeError, ValueError):
        return "invalid_task_payload"
    try:
        return celery_async_runtime.run(process_batch(parsed_id))
    except Exception:
        # Avoid serializing provider/database exception details to the broker.
        # Scheduled recovery remains available after broker retries exhaust.
        raise self.retry(countdown=60) from None


@celery_app.task(name=ECR_RECOVERY_TASK, queue="passport_ocr")  # type: ignore[untyped-decorator]
def recover_ecr_batches() -> str:
    count = celery_async_runtime.run(recover_batches())
    return f"dispatched={count}"


@celery_app.task(name=ECR_RETENTION_TASK, queue="passport_ocr")  # type: ignore[untyped-decorator]
def apply_ecr_retention() -> str:
    count = celery_async_runtime.run(apply_retention())
    return f"deleted_images={count}"
