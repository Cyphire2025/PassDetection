"""Autonomous bounded recovery of durable passport extraction intent."""

from __future__ import annotations

import asyncio

from fastapi import BackgroundTasks

from app.core.logging.logger import get_logger
from app.infrastructure.database.session import AsyncSessionFactory
from app.infrastructure.processing.dispatcher import PassportProcessingDispatcher
from app.infrastructure.processing.job_repository import PassportProcessingJobRepository

logger = get_logger(__name__)
RECOVERY_INTERVAL_SECONDS = 30.0
MAX_LOCAL_RECOVERIES = 2
_LOCAL_RECOVERIES: set[asyncio.Task[None]] = set()


def _finished(task: asyncio.Task[None]) -> None:
    _LOCAL_RECOVERIES.discard(task)
    if not task.cancelled() and (error := task.exception()) is not None:
        logger.warning("passport_extraction_recovery_task_failed", error_type=type(error).__name__)


async def recover_passport_extractions() -> int:
    """Recover without a status poll, request background task, or live broker."""
    capacity = MAX_LOCAL_RECOVERIES - len(_LOCAL_RECOVERIES)
    if capacity <= 0:
        return 0
    async with AsyncSessionFactory() as session:
        jobs = await PassportProcessingJobRepository(session).claim_recoverable_jobs(limit=capacity)
        await session.commit()
    dispatcher = PassportProcessingDispatcher()
    for job in jobs:
        background = BackgroundTasks()
        task_id = await dispatcher.dispatch_async(
            job_id=job.id,
            submission_id=job.submission_id,
            background_tasks=background,
        )
        # This includes the bounded delivery watchdog for accepted broker jobs.
        # Supervise every local task so errors are observed and process-local
        # fallbacks cannot accumulate without bound during an outage.
        task = asyncio.create_task(background(), name=f"passport-recovery:{job.id}")
        _LOCAL_RECOVERIES.add(task)
        task.add_done_callback(_finished)
        async with AsyncSessionFactory() as session:
            await PassportProcessingJobRepository(session).set_task_id(
                job.id, task_id or "local-background"
            )
            await session.commit()
    return len(jobs)


async def passport_extraction_recovery_loop() -> None:
    try:
        while True:
            try:
                await recover_passport_extractions()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("passport_extraction_recovery_failed", error_type=type(exc).__name__)
            await asyncio.sleep(RECOVERY_INTERVAL_SECONDS)
    finally:
        tasks = tuple(_LOCAL_RECOVERIES)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
