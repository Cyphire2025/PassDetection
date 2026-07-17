"""After-commit dispatch and watchdog for durable post-submit verification."""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from fastapi import BackgroundTasks

from app.core.config.settings import get_settings
from app.core.logging.logger import get_logger

logger = get_logger(__name__)
_LOCAL_RECOVERY_TASKS: set[asyncio.Task[None]] = set()


class PostSubmissionVerificationDispatcher:
    def __init__(self, backend: str | None = None) -> None:
        self._backend = backend or get_settings().processing_backend

    def dispatch(
        self,
        *,
        job_id: uuid.UUID,
        submission_id: uuid.UUID,
        verification_revision: int,
        background_tasks: BackgroundTasks,
    ) -> str | None:
        if self._backend == "celery":
            try:
                task = self._send_celery(
                    job_id=job_id,
                    submission_id=submission_id,
                    verification_revision=verification_revision,
                )
                background_tasks.add_task(
                    run_post_submission_verification_watchdog,
                    job_id=str(job_id),
                    submission_id=str(submission_id),
                    verification_revision=verification_revision,
                    delay_seconds=get_settings().processing_watchdog_delay_seconds,
                )
                return str(task.id)
            except Exception as exc:
                logger.warning(
                    "post_submission_verification_dispatch_local_fallback",
                    job_id=str(job_id),
                    error_type=type(exc).__name__,
                )

        background_tasks.add_task(
            _run_locally,
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

        # Reuse the deployed passport_ocr queue so no second worker topology is
        # required. Job type and revision remain independently persisted.
        return verify_submitted_passport.apply_async(
            kwargs={
                "job_id": str(job_id),
                "submission_id": str(submission_id),
                "verification_revision": verification_revision,
            },
            queue="passport_ocr",
            countdown=1,
        )


async def run_post_submission_verification_watchdog(
    *,
    job_id: str,
    submission_id: str,
    verification_revision: int,
    delay_seconds: float,
) -> None:
    await asyncio.sleep(delay_seconds)
    from app.infrastructure.database.session import AsyncSessionFactory
    from app.infrastructure.verification.job_repository import (
        PostSubmissionVerificationJobRepository,
    )

    async with AsyncSessionFactory() as session:
        job = await PostSubmissionVerificationJobRepository(session).get(uuid.UUID(job_id))
    if job is None or job.status != "queued":
        return
    logger.warning(
        "post_submission_verification_watchdog_local_fallback",
        job_id=job_id,
    )
    await _run_locally(
        job_id=job_id,
        submission_id=submission_id,
        verification_revision=verification_revision,
    )


async def recover_undispatched_post_submission_verifications() -> None:
    """Recover the durable after-commit gap after an API process restart."""

    from app.infrastructure.database.session import AsyncSessionFactory
    from app.infrastructure.verification.job_repository import (
        PostSubmissionVerificationJobRepository,
    )

    async with AsyncSessionFactory() as session:
        repository = PostSubmissionVerificationJobRepository(session)
        await repository.requeue_expired_running()
        jobs = await repository.queued_for_recovery()
        await session.commit()
    dispatcher = PostSubmissionVerificationDispatcher()
    for job in jobs:
        if dispatcher._backend == "celery":
            try:
                task = await asyncio.to_thread(
                    dispatcher._send_celery,
                    job_id=job.id,
                    submission_id=job.submission_id,
                    verification_revision=job.verification_revision,
                )
                async with AsyncSessionFactory() as session:
                    await PostSubmissionVerificationJobRepository(session).set_task_id(
                        job.id,
                        str(task.id),
                    )
                    await session.commit()
                continue
            except Exception as exc:
                logger.warning(
                    "post_submission_verification_outbox_publish_failed",
                    job_id=str(job.id),
                    error_type=type(exc).__name__,
                )
        task = asyncio.create_task(
            _run_locally(
                job_id=str(job.id),
                submission_id=str(job.submission_id),
                verification_revision=job.verification_revision,
            )
        )
        _LOCAL_RECOVERY_TASKS.add(task)
        task.add_done_callback(_LOCAL_RECOVERY_TASKS.discard)


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
        await asyncio.sleep(30)


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
