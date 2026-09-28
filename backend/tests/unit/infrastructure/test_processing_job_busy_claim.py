from __future__ import annotations

import unittest
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from app.infrastructure.processing.job_repository import (
    PassportProcessingJobRepository,
)


class PassportProcessingJobBusyClaimTests(unittest.IsolatedAsyncioTestCase):
    async def test_manual_busy_transition_only_applies_to_an_unstarted_job(self) -> None:
        for status, attempts, expected in (("queued", 0, True), ("queued", 1, False), ("running", 1, False), ("succeeded", 1, False)):
            with self.subTest(status=status, attempts=attempts):
                now = datetime.now(tz=UTC)
                model = SimpleNamespace(
                    id=uuid.uuid4(), submission_id=uuid.uuid4(), queue_name="interactive-passport-extraction",
                    status=status, attempts=attempts, max_attempts=3, extraction_revision=2,
                    progress=0.0, current_stage="queued", error_message=None,
                    celery_task_id=None, cancel_requested=False, created_at=now, updated_at=now,
                    started_at=None, finished_at=None,
                )
                query_result = Mock()
                query_result.scalar_one_or_none.return_value = model
                session = AsyncMock()
                session.execute.return_value = query_result
                job = await PassportProcessingJobRepository(session).mark_busy_if_unstarted(model.id, "busy")
                if expected:
                    self.assertIsNotNone(job)
                    self.assertEqual(model.status, "dead_letter")
                    self.assertEqual(model.current_stage, "extraction_busy")
                    self.assertEqual(model.attempts, 0)
                else:
                    self.assertIsNone(job)
                    self.assertEqual(model.status, status)
                    session.flush.assert_not_awaited()

    async def test_fresh_running_claim_does_not_consume_an_attempt(
        self,
    ) -> None:
        now = datetime.now(tz=UTC)
        model = SimpleNamespace(
            id=uuid.uuid4(),
            submission_id=uuid.uuid4(),
            queue_name="interactive-passport-extraction",
            status="running",
            attempts=1,
            max_attempts=3,
            extraction_revision=2,
            progress=0.1,
            current_stage="starting",
            error_message=None,
            celery_task_id="task-id",
            cancel_requested=False,
            created_at=now,
            updated_at=now,
            started_at=now,
            finished_at=None,
        )
        result = Mock()
        result.scalar_one_or_none.return_value = model
        session = AsyncMock()
        session.execute.return_value = result

        with patch(
            "app.infrastructure.processing.job_repository.get_settings",
            return_value=SimpleNamespace(
                processing_job_timeout_seconds=45,
            ),
        ):
            job, claimed = await PassportProcessingJobRepository(
                session
            ).claim_running(model.id)

        self.assertFalse(claimed)
        self.assertIsNotNone(job)
        assert job is not None
        self.assertEqual(job.attempts, 1)
        self.assertEqual(model.attempts, 1)
        session.flush.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
