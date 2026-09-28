"""Bound public extraction admission and preserve saved uploads for manual entry."""

from __future__ import annotations

import asyncio

from fastapi import BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.dtos.passport_dtos import (
    PassportSubmissionOutputDTO,
    passport_submission_output_from_entity,
)
from app.core.logging.logger import get_logger
from app.infrastructure.ai_priority import AiPriorityCoordinator, get_ai_priority_coordinator
from app.infrastructure.ai_priority.state import AdmissionDecision
from app.infrastructure.processing.job_repository import PassportProcessingJobRepository
from app.infrastructure.repositories.passport_submission_repository import (
    PassportSubmissionRepository,
)

from .processing_support import _dispatch_processing_job

PUBLIC_EXTRACTION_BUSY = (
    "Extraction is busy. Your passport images are saved. Fill in the details manually; "
    "AI verification will check them after you submit."
)
PUBLIC_ADMISSION_TIMEOUT_SECONDS = 1.0
logger = get_logger(__name__)


def _release_abandoned_reservation(
    priority: AiPriorityCoordinator, completed: asyncio.Task[AdmissionDecision],
) -> None:
    """Clean up even if a disconnected request never runs response background tasks."""

    try:
        late = completed.result()
    except (Exception, asyncio.CancelledError):
        logger.warning("public_extraction_abandoned_admission_failed")
        return
    if late.reason != "reserved":
        return
    cleanup = asyncio.get_running_loop().run_in_executor(
        None, priority.release_public_reservation, late.lease,
    )

    def inspect_cleanup(finished: asyncio.Future[bool]) -> None:
        try:
            if not finished.result():
                logger.warning("public_extraction_reservation_release_deferred")
        except (Exception, asyncio.CancelledError):
            logger.warning("public_extraction_reservation_release_failed")

    cleanup.add_done_callback(inspect_cleanup)


async def dispatch_public_extraction(
    result: PassportSubmissionOutputDTO,
    *, session: AsyncSession, background_tasks: BackgroundTasks,
) -> PassportSubmissionOutputDTO:
    """Return busy within a bounded scheduler wait after document persistence.

    The slot reservation is atomic across API processes and counts waiting,
    dispatched and active extractions, allowing one waiting batch beyond active
    capacity. Upload transfer/storage time is separate.
    """

    if not result.processing_job_id or result.processing_job_status != "queued":
        await session.commit()
        return result
    priority = get_ai_priority_coordinator()
    reservation = asyncio.create_task(asyncio.to_thread(
        priority.reserve_public_extraction, str(result.processing_job_id),
    ))
    decision: AdmissionDecision | None = None
    try:
        decision = await asyncio.wait_for(
            asyncio.shield(reservation), timeout=PUBLIC_ADMISSION_TIMEOUT_SECONDS,
        )
    except (TimeoutError, asyncio.CancelledError) as exc:
        # A thread cannot be cancelled while Redis is responding. Release only
        # a newly created late reservation; never release an existing worker.
        reservation.add_done_callback(lambda done: _release_abandoned_reservation(priority, done))
        if isinstance(exc, asyncio.CancelledError):
            raise

    if decision is not None and decision.admitted:
        try:
            await _dispatch_processing_job(
                result, session=session, background_tasks=background_tasks,
            )
        except BaseException:
            if decision.reason == "reserved":
                await asyncio.to_thread(priority.release_public_reservation, decision.lease)
            raise
        return result

    jobs = PassportProcessingJobRepository(session)
    job = await jobs.mark_busy_if_unstarted(result.processing_job_id, PUBLIC_EXTRACTION_BUSY)
    if job is None:
        # A replay may race a worker or recover an already-attempted internal
        # retry. Keep its durable delivery alive; do not turn it into busy.
        await _dispatch_processing_job(
            result, session=session, background_tasks=background_tasks,
        )
        return result
    submission = await PassportSubmissionRepository(session).apply_extraction_failure(
        submission_id=result.id, expected_revision=job.extraction_revision,
        public_message=PUBLIC_EXTRACTION_BUSY,
        diagnostics={"ai_verification": {
            "status": "unavailable", "available": False,
            "reason_code": "extraction_busy", "outcome_kind": "provider_failure",
            "extraction_revision": job.extraction_revision,
        }},
    )
    if submission is None:
        await jobs.mark_cancelled(job.id, "Superseded by newer passport changes")
    else:
        result = passport_submission_output_from_entity(submission, job=job)
    await session.commit()
    logger.info(
        "public_passport_extraction_busy",
        reason=decision.reason if decision else "admission_timeout",
        queued_and_active=decision.counts.extraction_pending_or_active if decision else None,
    )
    return result
