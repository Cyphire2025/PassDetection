"""Dispatch passport processing work to Celery or local background tasks."""

from __future__ import annotations

import asyncio
import uuid

from fastapi import BackgroundTasks

from app.core.config.settings import get_settings
from app.core.logging.logger import get_logger
from app.infrastructure.processing.tasks import process_passport_submission
from app.infrastructure.processing.worker_runtime import run_passport_processing_job_locally

logger = get_logger(__name__)


class PassportProcessingDispatcher:
    def __init__(self, backend: str | None = None) -> None:
        self._backend = backend or get_settings().processing_backend

    def dispatch(
        self,
        *,
        job_id: uuid.UUID,
        submission_id: uuid.UUID,
        background_tasks: BackgroundTasks | None = None,
    ) -> str | None:
        if self._backend == "celery":
            try:
                task = process_passport_submission.apply_async(
                    kwargs={"job_id": str(job_id), "submission_id": str(submission_id)},
                    queue="passport_ocr",
                    countdown=1,
                )
                logger.info(
                    "passport_processing_job_dispatched",
                    job_id=str(job_id),
                    celery_task_id=task.id,
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
                run_passport_processing_job_locally,
                job_id=str(job_id),
                submission_id=str(submission_id),
            )
        else:
            asyncio.create_task(
                run_passport_processing_job_locally(
                    job_id=str(job_id),
                    submission_id=str(submission_id),
                )
            )
        logger.info("passport_processing_job_dispatched_local", job_id=str(job_id))
        return None
