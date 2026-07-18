"""Dispatch passport processing work to Celery or local background tasks."""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from fastapi import BackgroundTasks

from app.core.config.settings import get_settings
from app.core.logging.logger import get_logger
from app.infrastructure.ai_priority import (
    EXTRACTION_QUEUE,
    AiPriorityCoordinator,
    get_ai_priority_coordinator,
)
from app.infrastructure.processing.delivery_watchdog import (
    run_passport_processing_job_watchdog,
)
from app.infrastructure.processing.job_state import ProcessingJobStatus

logger = get_logger(__name__)


class PassportProcessingDispatcher:
    def __init__(
        self,
        backend: str | None = None,
        *,
        priority_coordinator: AiPriorityCoordinator | None = None,
    ) -> None:
        self._backend = backend or get_settings().processing_backend
        self._priority = priority_coordinator or get_ai_priority_coordinator()

    def dispatch(
        self,
        *,
        job_id: uuid.UUID,
        submission_id: uuid.UUID,
        background_tasks: BackgroundTasks | None = None,
    ) -> str | None:
        priority_lease = self._priority.queue_extraction(str(job_id))
        if self._backend == "celery":
            try:
                task = self._send_celery(
                    job_id=job_id,
                    submission_id=submission_id,
                )
                logger.info(
                    "passport_processing_job_dispatched",
                    job_id=str(job_id),
                    celery_task_id=task.id,
                )
                self._priority.mark_extraction_dispatched(priority_lease)
                if background_tasks is not None:
                    settings = get_settings()
                    background_tasks.add_task(
                        run_passport_processing_job_watchdog,
                        job_id=str(job_id),
                        submission_id=str(submission_id),
                        delay_seconds=settings.processing_watchdog_delay_seconds,
                        ping_timeout_seconds=settings.processing_worker_ping_timeout_seconds,
                    )
                return str(task.id)
            except Exception as exc:
                # File and database persistence already succeeded. A broker
                # outage must not be reported to the traveller as an upload
                # failure, so fall back to the bounded local runner.
                logger.warning(
                    "passport_processing_dispatch_fell_back_local",
                    job_id=str(job_id),
                    error_type=type(exc).__name__,
                )

        if background_tasks is not None:
            background_tasks.add_task(
                _run_passport_processing_job_locally,
                job_id=str(job_id),
                submission_id=str(submission_id),
            )
        else:
            asyncio.create_task(
                _run_passport_processing_job_locally(
                    job_id=str(job_id),
                    submission_id=str(submission_id),
                )
            )
        logger.info("passport_processing_job_dispatched_local", job_id=str(job_id))
        return None

    @staticmethod
    def _send_celery(
        *,
        job_id: uuid.UUID,
        submission_id: uuid.UUID,
    ) -> Any:
        from app.infrastructure.processing.tasks import process_passport_submission

        return process_passport_submission.apply_async(
            kwargs={"job_id": str(job_id), "submission_id": str(submission_id)},
            queue=EXTRACTION_QUEUE,
            countdown=1,
        )


async def _run_passport_processing_job_locally(
    *,
    job_id: str,
    submission_id: str,
) -> None:
    from app.infrastructure.processing.worker_runtime import (
        run_passport_processing_job_locally,
    )

    await run_passport_processing_job_locally(
        job_id=job_id,
        submission_id=submission_id,
    )


def queued_job_needs_redelivery(job: Any) -> bool:
    return (
        job.status == ProcessingJobStatus.QUEUED
        and job.celery_task_id in {None, "", "local-background"}
    )
