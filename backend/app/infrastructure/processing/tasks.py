"""Celery task definitions for passport processing."""

from __future__ import annotations

import asyncio

from celery.utils.log import get_task_logger

from app.application.use_cases.passports.process_passport_submission_job_use_case import (
    ProcessingRetryRequested,
)
from app.infrastructure.processing.celery_app import celery_app
from app.infrastructure.processing.worker_runtime import run_passport_processing_job

logger = get_task_logger(__name__)


@celery_app.task(
    bind=True,
    name="passport.process_submission",
    queue="passport_ocr",
    max_retries=2,
    default_retry_delay=5,
)
def process_passport_submission(self, *, job_id: str, submission_id: str) -> None:  # type: ignore[no-untyped-def]
    try:
        asyncio.run(run_passport_processing_job(job_id=job_id, submission_id=submission_id))
    except ProcessingRetryRequested as exc:
        countdown = min(30, 2 ** self.request.retries * 5)
        raise self.retry(exc=exc, countdown=countdown) from exc
    except Exception:
        logger.exception(
            "celery_passport_processing_task_failed job_id=%s submission_id=%s",
            job_id,
            submission_id,
        )
        raise
