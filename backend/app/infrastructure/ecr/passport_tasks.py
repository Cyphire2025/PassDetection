"""Small passport ECR drains share the dedicated Documents ECR worker."""

from __future__ import annotations

from typing import Any

from app.infrastructure.celery_async_runtime import celery_async_runtime
from app.infrastructure.ecr import ECR_QUEUE, PASSPORT_ECR_RECOVERY_TASK, PASSPORT_ECR_TASK
from app.infrastructure.ecr.passport_runtime import (
    MAX_PASSPORT_DRAIN,
    process_passport_checks,
    recover_passport_checks,
)
from app.infrastructure.processing.celery_app import celery_app


@celery_app.task(
    bind=True,
    name=PASSPORT_ECR_TASK,
    queue=ECR_QUEUE,
    max_retries=5,
    soft_time_limit=9 * 60,
    time_limit=10 * 60,
)  # type: ignore[untyped-decorator]
def process_passport_ecr_checks(self: Any) -> str:
    try:
        count = celery_async_runtime.run(process_passport_checks())
        if count == MAX_PASSPORT_DRAIN:
            celery_app.send_task(PASSPORT_ECR_TASK, queue=ECR_QUEUE)
        return f"processed={count}"
    except Exception:
        raise self.retry(countdown=60) from None


@celery_app.task(
    name=PASSPORT_ECR_RECOVERY_TASK, queue="passport_ocr", soft_time_limit=210, time_limit=240
)  # type: ignore[untyped-decorator]
def recover_passport_ecr_checks() -> str:
    count = celery_async_runtime.run(recover_passport_checks())
    return f"staged={count}"
