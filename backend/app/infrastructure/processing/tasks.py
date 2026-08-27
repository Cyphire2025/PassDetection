"""Celery task definitions for passport processing."""

from __future__ import annotations

from typing import Protocol

from celery.exceptions import Reject
from celery.utils.log import get_task_logger

from app.application.use_cases.passports.process_passport_submission_job_use_case import (
    ProcessingJobBusy,
    ProcessingRetryRequested,
)
from app.core.config.settings import get_settings
from app.infrastructure.ai_priority import (
    EXTRACTION_QUEUE,
    AiPriorityAdmissionDeferred,
)
from app.infrastructure.celery_async_runtime import celery_async_runtime
from app.infrastructure.processing.celery_app import celery_app
from app.infrastructure.processing.worker_runtime import run_passport_processing_job

logger = get_task_logger(__name__)


class _BoundTaskRequest(Protocol):
    retries: int


class _BoundTask(Protocol):
    request: _BoundTaskRequest

    def retry(self, *, exc: BaseException, countdown: int) -> BaseException: ...


@celery_app.task(  # type: ignore[untyped-decorator]  # Celery exposes an untyped task decorator.
    bind=True,
    name="passport.process_submission",
    queue=EXTRACTION_QUEUE,
    max_retries=max(0, get_settings().processing_job_max_attempts - 1),
    default_retry_delay=5,
)
def process_passport_submission(
    self: _BoundTask,
    *,
    job_id: str,
    submission_id: str,
) -> None:
    try:
        celery_async_runtime.run(
            run_passport_processing_job(
                job_id=job_id,
                submission_id=submission_id,
            )
        )
    except (AiPriorityAdmissionDeferred, ProcessingJobBusy) as exc:
        # Scheduler and fresh RUNNING-claim deferrals are not provider
        # attempts. Publish a new delivery so they never consume the durable
        # provider retry budget.
        try:
            process_passport_submission.apply_async(
                kwargs={"job_id": job_id, "submission_id": submission_id},
                queue=EXTRACTION_QUEUE,
                countdown=max(1, (exc.retry_after_ms + 999) // 1_000),
            )
        except Exception as publish_exc:
            # The durable row still needs a delivery. Rejecting the current
            # late-acked message avoids an ACK-and-strand window.
            raise Reject(
                (f"AI admission redelivery publish failed: {type(publish_exc).__name__}"),
                requeue=True,
            ) from publish_exc
        return
    except ProcessingRetryRequested as exc:
        countdown = min(30, 2**self.request.retries * 5)
        raise self.retry(exc=exc, countdown=countdown) from exc
    except Exception as exc:
        logger.error(
            "celery_passport_processing_task_failed",
            job_id=job_id,
            submission_id=submission_id,
            error_type=type(exc).__name__,
        )
        raise
