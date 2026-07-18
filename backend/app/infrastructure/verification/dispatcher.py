"""After-commit dispatch and watchdog for durable post-submit verification."""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from fastapi import BackgroundTasks

from app.core.config.settings import get_settings
from app.core.logging.logger import get_logger
from app.infrastructure.ai_priority import (
    VERIFICATION_QUEUE,
    AiPriorityCoordinator,
    get_ai_priority_coordinator,
)

logger = get_logger(__name__)
_RECOVERY_BATCH_LIMIT = 100
_RECOVERY_INTERVAL_SECONDS = 30.0
_MAX_LOCAL_RECOVERY_TASKS = 2
_LOCAL_RECOVERY_TASKS: dict[str, asyncio.Task[None]] = {}


class PostSubmissionVerificationDispatcher:
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
        verification_revision: int,
        background_tasks: BackgroundTasks,
    ) -> str | None:
        self._priority.queue_verification(str(job_id))
        if self._backend == "celery":
            try:
                task = self._send_celery(
                    job_id=job_id,
                    submission_id=submission_id,
                    verification_revision=verification_revision,
                )
                return str(task.id)
            except Exception as exc:
                logger.warning(
                    "post_submission_verification_dispatch_local_fallback",
                    job_id=str(job_id),
                    error_type=type(exc).__name__,
                )

        background_tasks.add_task(
            _schedule_local_recovery,
            job_id=str(job_id),
            submission_id=str(submission_id),
            verification_revision=verification_revision,
        )
        return None

    @staticmethod
    def _send_celery(
        *,
        job_id: uuid.UUID,
        submission_id: uuid.UUID,
        verification_revision: int,
    ) -> Any:
        from app.infrastructure.verification.tasks import (
            verify_submitted_passport,
        )

        return verify_submitted_passport.apply_async(
            kwargs={
                "job_id": str(job_id),
                "submission_id": str(submission_id),
                "verification_revision": verification_revision,
            },
            queue=VERIFICATION_QUEUE,
            countdown=1,
        )


async def recover_undispatched_post_submission_verifications() -> None:
    """Recover only stale durable delivery gaps with bounded API-local work."""

    jobs = await _recoverable_jobs()
    if not jobs:
        return

    dispatcher = PostSubmissionVerificationDispatcher()
    worker_available = False
    if dispatcher._backend == "celery":
        worker_available = await _worker_available(
            get_settings().processing_worker_ping_timeout_seconds
        )

    for job in jobs:
        dispatcher._priority.queue_verification(str(job.id))
        if dispatcher._backend == "celery" and worker_available:
            try:
                task = await asyncio.to_thread(
                    dispatcher._send_celery,
                    job_id=job.id,
                    submission_id=job.submission_id,
                    verification_revision=job.verification_revision,
                )
                await _persist_task_id(job.id, str(task.id))
                continue
            except Exception as exc:
                logger.warning(
                    "post_submission_verification_outbox_publish_failed",
                    job_id=str(job.id),
                    error_type=type(exc).__name__,
                )

        await _schedule_local_recovery(
            job_id=str(job.id),
            submission_id=str(job.submission_id),
            verification_revision=job.verification_revision,
        )


async def post_submission_verification_recovery_loop() -> None:
    """Continuously close API-commit-to-dispatch gaps after process failures."""

    while True:
        try:
            await recover_undispatched_post_submission_verifications()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning(
                "post_submission_verification_recovery_failed",
                error_type=type(exc).__name__,
            )
        await asyncio.sleep(_RECOVERY_INTERVAL_SECONDS)


async def _recoverable_jobs() -> list[Any]:
    """Release expired leases and load only old queued delivery gaps."""

    from app.infrastructure.database.session import AsyncSessionFactory
    from app.infrastructure.verification.job_repository import (
        PostSubmissionVerificationJobRepository,
    )

    async with AsyncSessionFactory() as session:
        repository = PostSubmissionVerificationJobRepository(session)
        await repository.requeue_expired_running(limit=_RECOVERY_BATCH_LIMIT)
        jobs = await repository.queued_for_recovery(limit=_RECOVERY_BATCH_LIMIT)
        await session.commit()
    return jobs


async def _persist_task_id(job_id: uuid.UUID, task_id: str) -> None:
    from app.infrastructure.database.session import AsyncSessionFactory
    from app.infrastructure.verification.job_repository import (
        PostSubmissionVerificationJobRepository,
    )

    try:
        async with AsyncSessionFactory() as session:
            await PostSubmissionVerificationJobRepository(session).set_task_id(
                job_id,
                task_id,
            )
            await session.commit()
    except Exception as exc:
        logger.warning(
            "post_submission_verification_task_id_recovery_persist_failed",
            job_id=str(job_id),
            error_type=type(exc).__name__,
        )


async def _worker_available(timeout_seconds: float) -> bool:
    return await asyncio.to_thread(
        _celery_worker_available,
        timeout_seconds,
    )


def _celery_worker_available(timeout_seconds: float) -> bool:
    try:
        from app.infrastructure.processing.celery_app import celery_app

        replies = celery_app.control.ping(timeout=timeout_seconds)
    except Exception as exc:
        logger.warning(
            "post_submission_verification_worker_healthcheck_failed",
            error_type=type(exc).__name__,
        )
        return False
    return bool(replies)


async def _schedule_local_recovery(
    *,
    job_id: str,
    submission_id: str,
    verification_revision: int,
) -> bool:
    """Start at most one local task per job and cap process-local recovery."""

    existing = _LOCAL_RECOVERY_TASKS.get(job_id)
    if existing is not None and not existing.done():
        logger.info(
            "post_submission_verification_local_recovery_duplicate_suppressed",
            job_id=job_id,
        )
        return False
    if existing is not None:
        _LOCAL_RECOVERY_TASKS.pop(job_id, None)

    if len(_LOCAL_RECOVERY_TASKS) >= _MAX_LOCAL_RECOVERY_TASKS:
        logger.warning(
            "post_submission_verification_local_recovery_capacity_reached",
            job_id=job_id,
            active_local_recoveries=len(_LOCAL_RECOVERY_TASKS),
        )
        return False

    task = asyncio.create_task(
        _run_locally(
            job_id=job_id,
            submission_id=submission_id,
            verification_revision=verification_revision,
        ),
        name=f"post-submission-verification-recovery:{job_id}",
    )
    _LOCAL_RECOVERY_TASKS[job_id] = task

    def complete_local_recovery(completed: asyncio.Task[None]) -> None:
        _local_recovery_done(job_id, completed)

    task.add_done_callback(complete_local_recovery)
    return True


def _local_recovery_done(job_id: str, task: asyncio.Task[None]) -> None:
    if _LOCAL_RECOVERY_TASKS.get(job_id) is task:
        _LOCAL_RECOVERY_TASKS.pop(job_id, None)
    if task.cancelled():
        return
    error = task.exception()
    if error is not None:
        logger.warning(
            "post_submission_verification_local_recovery_failed",
            job_id=job_id,
            error_type=type(error).__name__,
        )


async def _run_locally(
    *,
    job_id: str,
    submission_id: str,
    verification_revision: int,
) -> None:
    from app.infrastructure.verification.runtime import (
        run_post_submission_verification_locally,
    )

    await run_post_submission_verification_locally(
        job_id=job_id,
        submission_id=submission_id,
        verification_revision=verification_revision,
    )
