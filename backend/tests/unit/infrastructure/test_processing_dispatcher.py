from __future__ import annotations

import os
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import BackgroundTasks

os.environ.setdefault("APP_SECRET_KEY", "unit-test-secret")

from app.infrastructure.processing.delivery_watchdog import (
    run_passport_processing_job_watchdog,
)
from app.infrastructure.processing.dispatcher import (
    PassportProcessingDispatcher,
    _run_passport_processing_job_locally,
    queued_job_needs_redelivery,
)
from app.infrastructure.processing.job_state import ProcessingJobStatus


class PassportProcessingDispatcherTests(unittest.TestCase):
    def test_celery_delivery_registers_a_local_queued_job_watchdog(self) -> None:
        job_id = uuid.uuid4()
        submission_id = uuid.uuid4()
        background_tasks = BackgroundTasks()

        with (
            patch(
                "app.infrastructure.processing.dispatcher."
                "PassportProcessingDispatcher._send_celery",
                return_value=SimpleNamespace(id="celery-task-id"),
            ) as send_celery,
            patch(
                "app.infrastructure.processing.dispatcher.get_settings",
                return_value=SimpleNamespace(
                    processing_watchdog_delay_seconds=8.0,
                    processing_worker_ping_timeout_seconds=1.0,
                ),
            ),
        ):
            task_id = PassportProcessingDispatcher(backend="celery").dispatch(
                job_id=job_id,
                submission_id=submission_id,
                background_tasks=background_tasks,
        )

        self.assertEqual(task_id, "celery-task-id")
        send_celery.assert_called_once()
        self.assertEqual(len(background_tasks.tasks), 1)
        watchdog = background_tasks.tasks[0]
        self.assertIs(watchdog.func, run_passport_processing_job_watchdog)
        self.assertEqual(watchdog.kwargs["job_id"], str(job_id))
        self.assertEqual(watchdog.kwargs["submission_id"], str(submission_id))
        self.assertEqual(watchdog.kwargs["delay_seconds"], 8.0)
        self.assertEqual(watchdog.kwargs["ping_timeout_seconds"], 1.0)

    def test_broker_failure_falls_back_to_local_background_processing(self) -> None:
        job_id = uuid.uuid4()
        submission_id = uuid.uuid4()
        background_tasks = BackgroundTasks()

        with patch(
            "app.infrastructure.processing.dispatcher."
            "PassportProcessingDispatcher._send_celery",
            side_effect=ConnectionError("broker unavailable"),
        ):
            task_id = PassportProcessingDispatcher(backend="celery").dispatch(
                job_id=job_id,
                submission_id=submission_id,
                background_tasks=background_tasks,
            )

        self.assertIsNone(task_id)
        self.assertEqual(len(background_tasks.tasks), 1)
        fallback = background_tasks.tasks[0]
        self.assertIs(fallback.func, _run_passport_processing_job_locally)
        self.assertEqual(fallback.kwargs["job_id"], str(job_id))
        self.assertEqual(fallback.kwargs["submission_id"], str(submission_id))

    def test_poll_redelivery_recovers_missing_or_unstarted_local_delivery(self) -> None:
        for task_id in (None, "", "local-background"):
            with self.subTest(task_id=task_id):
                self.assertTrue(
                    queued_job_needs_redelivery(
                        SimpleNamespace(
                            status=ProcessingJobStatus.QUEUED,
                            celery_task_id=task_id,
                        )
                    )
                )

        self.assertFalse(
            queued_job_needs_redelivery(
                SimpleNamespace(
                    status=ProcessingJobStatus.QUEUED,
                    celery_task_id="real-celery-task-id",
                )
            )
        )
        self.assertFalse(
            queued_job_needs_redelivery(
                SimpleNamespace(
                    status=ProcessingJobStatus.RUNNING,
                    celery_task_id="local-background",
                )
            )
        )


if __name__ == "__main__":
    unittest.main()
