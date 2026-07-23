"""Celery entry point for durable Visa-photo AI generation."""

from __future__ import annotations

from celery.utils.log import get_task_logger

from app.core.config.settings import get_settings
from app.infrastructure.celery_async_runtime import celery_async_runtime
from app.infrastructure.processing.celery_app import celery_app
from app.infrastructure.visa_ai_image_jobs import (
    VISA_AI_IMAGE_QUEUE,
    VISA_AI_IMAGE_TASK,
)
from app.infrastructure.visa_ai_image_jobs.runtime import (
    VisaAiImageJobRetryRequested,
    run_visa_ai_image_job,
)

logger = get_task_logger(__name__)


@celery_app.task(
    bind=True,
    name=VISA_AI_IMAGE_TASK,
    queue=VISA_AI_IMAGE_QUEUE,
    max_retries=max(0, get_settings().gemini_image_edit_job_max_attempts - 1),
    default_retry_delay=15,
)
def generate_visa_ai_image(self, *, job_id: str, submission_id: str) -> None:  # type: ignore[no-untyped-def]
    try:
        celery_async_runtime.run(
            run_visa_ai_image_job(
                job_id=job_id,
                submission_id=submission_id,
            )
        )
    except VisaAiImageJobRetryRequested as exc:
        countdown = min(45, 15 * (self.request.retries + 1))
        raise self.retry(exc=exc, countdown=countdown) from exc
    except Exception as exc:
        logger.error(
            "visa_ai_image_celery_task_failed",
            job_id=job_id,
            submission_id=submission_id,
            error_type=type(exc).__name__,
        )
        raise
