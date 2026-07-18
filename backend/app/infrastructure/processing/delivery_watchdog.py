"""Bounded recovery for durable jobs when no Celery worker is available."""

from __future__ import annotations

import asyncio
import uuid

from app.core.logging.logger import get_logger
from app.infrastructure.ai_priority import (
    EXTRACTION_QUEUE,
    get_ai_priority_coordinator,
)
from app.infrastructure.ai_priority.worker_readiness import (
    celery_queue_available,
)
from app.infrastructure.processing.job_state import ProcessingJobStatus

logger = get_logger(__name__)


async def run_passport_processing_job_watchdog(
    *,
    job_id: str,
    submission_id: str,
    delay_seconds: float,
    ping_timeout_seconds: float,
) -> None:
    """Use the API process only when a queued job has no healthy worker."""

    await asyncio.sleep(delay_seconds)
    if await _queued_job_status(job_id) != ProcessingJobStatus.QUEUED:
        return
    if await _worker_available(ping_timeout_seconds):
        # A live worker with a still-queued durable row may indicate that the
        # original broker publish was lost. Re-deliver to Celery once; never
        # pull ordinary worker backlog into the API process.
        await _redeliver_to_worker(job_id=job_id, submission_id=submission_id)
        return

    # Re-read after the network health check so a worker that claimed the job
    # during the ping window always wins.
    if await _queued_job_status(job_id) != ProcessingJobStatus.QUEUED:
        return
    logger.warning(
        "passport_processing_watchdog_using_local_fallback",
        job_id=job_id,
    )
    await _run_locally(job_id=job_id, submission_id=submission_id)


async def _worker_available(timeout_seconds: float) -> bool:
    return await asyncio.to_thread(
        _celery_worker_available,
        timeout_seconds,
    )


def _celery_worker_available(timeout_seconds: float) -> bool:
    try:
        return celery_queue_available(
            EXTRACTION_QUEUE,
            timeout_seconds=timeout_seconds,
        )
    except Exception as exc:
        logger.warning(
            "passport_processing_worker_healthcheck_failed",
            error_type=type(exc).__name__,
        )
        return False


async def _queued_job_status(job_id: str) -> ProcessingJobStatus | None:
    # Keep database/runtime imports lazy so dispatcher startup and unit tests do
    # not instantiate a second engine merely by importing this watchdog.
    from app.infrastructure.database.session import AsyncSessionFactory
    from app.infrastructure.processing.job_repository import (
        PassportProcessingJobRepository,
    )

    async with AsyncSessionFactory() as session:
        job = await PassportProcessingJobRepository(session).get(uuid.UUID(job_id))
    return job.status if job is not None else None


async def _run_locally(*, job_id: str, submission_id: str) -> None:
    from app.infrastructure.processing.worker_runtime import (
        run_passport_processing_job_locally,
    )

    await run_passport_processing_job_locally(
        job_id=job_id,
        submission_id=submission_id,
    )


async def _redeliver_to_worker(*, job_id: str, submission_id: str) -> None:
    try:
        await asyncio.to_thread(
            _send_to_worker,
            job_id,
            submission_id,
        )
    except Exception as exc:
        logger.warning(
            "passport_processing_watchdog_redelivery_failed",
            job_id=job_id,
            error_type=type(exc).__name__,
        )


def _send_to_worker(job_id: str, submission_id: str) -> None:
    from app.infrastructure.processing.tasks import process_passport_submission

    priority = get_ai_priority_coordinator()
    lease = priority.queue_extraction(job_id)
    process_passport_submission.apply_async(
        kwargs={"job_id": job_id, "submission_id": submission_id},
        queue=EXTRACTION_QUEUE,
    )
    priority.mark_extraction_dispatched(lease)
