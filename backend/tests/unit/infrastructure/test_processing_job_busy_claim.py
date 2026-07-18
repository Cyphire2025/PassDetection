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
