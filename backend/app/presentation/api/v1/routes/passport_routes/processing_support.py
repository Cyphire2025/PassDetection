"""Passport processing support: focused workflow boundary."""

from __future__ import annotations

from fastapi import BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.dtos.passport_dtos import PassportSubmissionOutputDTO
from app.core.logging.logger import get_logger
from app.infrastructure.processing.dispatcher import PassportProcessingDispatcher
from app.infrastructure.processing.job_repository import PassportProcessingJobRepository

logger = get_logger(__name__)


async def _dispatch_processing_job(
    result: PassportSubmissionOutputDTO,
    *,
    session: AsyncSession,
    background_tasks: BackgroundTasks,
) -> None:
    if not result.processing_job_id:
        return

    # The worker uses a separate database session, so commit the queued rows
    # before dispatching to avoid a race with the worker reading the job.
    await session.commit()
    try:
        task_id = await PassportProcessingDispatcher().dispatch_async(
            job_id=result.processing_job_id,
            submission_id=result.id,
            background_tasks=background_tasks,
        )
    except Exception as exc:
        # The submission and image keys are durable at this point. Dispatch is
        # best effort and must never turn persistence success into an upload
        # failure (or trigger compensation that deletes committed objects).
        logger.error(
            "passport_processing_dispatch_failed_after_persistence",
            job_id=str(result.processing_job_id),
            error_type=type(exc).__name__,
        )
        return
    try:
        await PassportProcessingJobRepository(session).set_task_id(
            result.processing_job_id,
            task_id or "local-background",
        )
        await session.commit()
    except Exception as exc:
        # The submission and job were already committed before dispatch.
        # Losing optional queue metadata must not turn a successful upload
        # into a reported upload failure.
        await session.rollback()
        logger.warning(
            "passport_processing_task_id_not_recorded",
            job_id=str(result.processing_job_id),
            error_type=type(exc).__name__,
        )
