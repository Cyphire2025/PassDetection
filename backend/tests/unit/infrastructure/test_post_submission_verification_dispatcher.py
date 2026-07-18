from __future__ import annotations

import asyncio
import os
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import BackgroundTasks

os.environ.setdefault("APP_SECRET_KEY", "unit-test-secret")

from app.infrastructure.verification import dispatcher as verification_dispatcher
from app.infrastructure.verification.dispatcher import (
    PostSubmissionVerificationDispatcher,
    _schedule_local_recovery,
    recover_undispatched_post_submission_verifications,
)


class _Priority:
    def __init__(self) -> None:
        self.queued: list[str] = []

    def queue_verification(self, job_reference: str) -> object:
        self.queued.append(job_reference)
        return object()


def _job() -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        submission_id=uuid.uuid4(),
        verification_revision=1,
    )


class PostSubmissionVerificationDispatchTests(unittest.TestCase):
    def test_healthy_celery_delivery_creates_no_api_local_watchdog(self) -> None:
        job = _job()
        background_tasks = BackgroundTasks()
        priority = _Priority()

        with patch.object(
            PostSubmissionVerificationDispatcher,
            "_send_celery",
            return_value=SimpleNamespace(id="celery-task-id"),
        ):
            task_id = PostSubmissionVerificationDispatcher(
                backend="celery",
                priority_coordinator=priority,  # type: ignore[arg-type]
            ).dispatch(
                job_id=job.id,
                submission_id=job.submission_id,
                verification_revision=job.verification_revision,
                background_tasks=background_tasks,
            )

        self.assertEqual(task_id, "celery-task-id")
        self.assertEqual(priority.queued, [str(job.id)])
        self.assertEqual(background_tasks.tasks, [])

    def test_broker_failure_registers_only_bounded_local_recovery(self) -> None:
        job = _job()
        background_tasks = BackgroundTasks()

        with patch.object(
            PostSubmissionVerificationDispatcher,
            "_send_celery",
            side_effect=ConnectionError("broker unavailable"),
        ):
            task_id = PostSubmissionVerificationDispatcher(
                backend="celery",
                priority_coordinator=_Priority(),  # type: ignore[arg-type]
            ).dispatch(
                job_id=job.id,
                submission_id=job.submission_id,
                verification_revision=job.verification_revision,
                background_tasks=background_tasks,
            )

        self.assertIsNone(task_id)
        self.assertEqual(len(background_tasks.tasks), 1)
        recovery = background_tasks.tasks[0]
        self.assertIs(recovery.func, _schedule_local_recovery)
        self.assertEqual(recovery.kwargs["job_id"], str(job.id))


class PostSubmissionVerificationRecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncTearDown(self) -> None:
        tasks = list(verification_dispatcher._LOCAL_RECOVERY_TASKS.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        verification_dispatcher._LOCAL_RECOVERY_TASKS.clear()

    async def test_healthy_worker_redelivers_stale_job_without_local_execution(
        self,
    ) -> None:
        job = _job()
        priority = _Priority()
        send_celery = MagicMock(return_value=SimpleNamespace(id="redelivered-task"))
        dispatcher = SimpleNamespace(
            _backend="celery",
            _priority=priority,
            _send_celery=send_celery,
        )

        with (
            patch(
                "app.infrastructure.verification.dispatcher._recoverable_jobs",
                new=AsyncMock(return_value=[job]),
            ),
            patch(
                "app.infrastructure.verification.dispatcher."
                "PostSubmissionVerificationDispatcher",
                return_value=dispatcher,
            ),
            patch(
                "app.infrastructure.verification.dispatcher.get_settings",
                return_value=SimpleNamespace(
                    processing_worker_ping_timeout_seconds=1.0
                ),
            ),
            patch(
                "app.infrastructure.verification.dispatcher._worker_available",
                new=AsyncMock(return_value=True),
            ),
            patch(
                "app.infrastructure.verification.dispatcher._persist_task_id",
                new=AsyncMock(),
            ) as persist_task_id,
            patch(
                "app.infrastructure.verification.dispatcher."
                "_schedule_local_recovery",
                new=AsyncMock(),
            ) as schedule_local,
        ):
            await recover_undispatched_post_submission_verifications()

        self.assertEqual(priority.queued, [str(job.id)])
        send_celery.assert_called_once()
        persist_task_id.assert_awaited_once_with(job.id, "redelivered-task")
        schedule_local.assert_not_awaited()

    async def test_stale_job_recovers_locally_when_broker_publish_fails(
        self,
    ) -> None:
        job = _job()
        dispatcher = SimpleNamespace(
            _backend="celery",
            _priority=_Priority(),
            _send_celery=MagicMock(
                side_effect=ConnectionError("broker unavailable")
            ),
        )

        with (
            patch(
                "app.infrastructure.verification.dispatcher._recoverable_jobs",
                new=AsyncMock(return_value=[job]),
            ),
            patch(
                "app.infrastructure.verification.dispatcher."
                "PostSubmissionVerificationDispatcher",
                return_value=dispatcher,
            ),
            patch(
                "app.infrastructure.verification.dispatcher.get_settings",
                return_value=SimpleNamespace(
                    processing_worker_ping_timeout_seconds=1.0
                ),
            ),
            patch(
                "app.infrastructure.verification.dispatcher._worker_available",
                new=AsyncMock(return_value=True),
            ),
            patch(
                "app.infrastructure.verification.dispatcher."
                "_schedule_local_recovery",
                new=AsyncMock(return_value=True),
            ) as schedule_local,
        ):
            await recover_undispatched_post_submission_verifications()

        schedule_local.assert_awaited_once_with(
            job_id=str(job.id),
            submission_id=str(job.submission_id),
            verification_revision=job.verification_revision,
        )

    async def test_duplicate_local_recovery_for_same_job_is_suppressed(
        self,
    ) -> None:
        release = asyncio.Event()

        async def wait_for_release(**_kwargs: object) -> None:
            await release.wait()

        job = _job()
        with patch(
            "app.infrastructure.verification.dispatcher._run_locally",
            new=AsyncMock(side_effect=wait_for_release),
        ) as run_locally:
            first = await _schedule_local_recovery(
                job_id=str(job.id),
                submission_id=str(job.submission_id),
                verification_revision=job.verification_revision,
            )
            duplicate = await _schedule_local_recovery(
                job_id=str(job.id),
                submission_id=str(job.submission_id),
                verification_revision=job.verification_revision,
            )
            await asyncio.sleep(0)

            self.assertTrue(first)
            self.assertFalse(duplicate)
            self.assertEqual(run_locally.await_count, 1)
            self.assertEqual(
                list(verification_dispatcher._LOCAL_RECOVERY_TASKS),
                [str(job.id)],
            )
            release.set()
            await asyncio.gather(
                *verification_dispatcher._LOCAL_RECOVERY_TASKS.values()
            )

    async def test_unhealthy_worker_recovery_is_bounded_per_api_process(
        self,
    ) -> None:
        release = asyncio.Event()

        async def wait_for_release(**_kwargs: object) -> None:
            await release.wait()

        jobs = [_job(), _job(), _job()]
        priority = _Priority()
        dispatcher = SimpleNamespace(
            _backend="celery",
            _priority=priority,
            _send_celery=MagicMock(),
        )

        with (
            patch(
                "app.infrastructure.verification.dispatcher._recoverable_jobs",
                new=AsyncMock(return_value=jobs),
            ),
            patch(
                "app.infrastructure.verification.dispatcher."
                "PostSubmissionVerificationDispatcher",
                return_value=dispatcher,
            ),
            patch(
                "app.infrastructure.verification.dispatcher.get_settings",
                return_value=SimpleNamespace(
                    processing_worker_ping_timeout_seconds=1.0
                ),
            ),
            patch(
                "app.infrastructure.verification.dispatcher._worker_available",
                new=AsyncMock(return_value=False),
            ),
            patch(
                "app.infrastructure.verification.dispatcher."
                "_MAX_LOCAL_RECOVERY_TASKS",
                2,
            ),
            patch(
                "app.infrastructure.verification.dispatcher._run_locally",
                new=AsyncMock(side_effect=wait_for_release),
            ) as run_locally,
        ):
            await recover_undispatched_post_submission_verifications()
            await asyncio.sleep(0)

            self.assertEqual(priority.queued, [str(job.id) for job in jobs])
            self.assertEqual(run_locally.await_count, 2)
            self.assertEqual(
                len(verification_dispatcher._LOCAL_RECOVERY_TASKS),
                2,
            )
            release.set()
            await asyncio.gather(
                *verification_dispatcher._LOCAL_RECOVERY_TASKS.values()
            )


if __name__ == "__main__":
    unittest.main()
