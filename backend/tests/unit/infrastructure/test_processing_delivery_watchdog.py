from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from app.infrastructure.processing.delivery_watchdog import (
    run_passport_processing_job_watchdog,
)
from app.infrastructure.processing.job_state import ProcessingJobStatus


class PassportProcessingDeliveryWatchdogTests(unittest.IsolatedAsyncioTestCase):
    async def test_healthy_worker_keeps_queued_job_out_of_web_process(self) -> None:
        with (
            patch(
                "app.infrastructure.processing.delivery_watchdog.asyncio.sleep",
                new=AsyncMock(),
            ),
            patch(
                "app.infrastructure.processing.delivery_watchdog._queued_job_status",
                new=AsyncMock(return_value=ProcessingJobStatus.QUEUED),
            ),
            patch(
                "app.infrastructure.processing.delivery_watchdog._worker_available",
                new=AsyncMock(return_value=True),
            ),
            patch(
                "app.infrastructure.processing.delivery_watchdog._run_locally",
                new=AsyncMock(),
            ) as run_locally,
            patch(
                "app.infrastructure.processing.delivery_watchdog._redeliver_to_worker",
                new=AsyncMock(),
            ) as redeliver,
        ):
            await run_passport_processing_job_watchdog(
                job_id="00000000-0000-0000-0000-000000000001",
                submission_id="00000000-0000-0000-0000-000000000002",
                delay_seconds=8.0,
                ping_timeout_seconds=1.0,
            )

        run_locally.assert_not_awaited()
        redeliver.assert_awaited_once()

    async def test_missing_worker_runs_still_queued_job_locally(self) -> None:
        queued_status = AsyncMock(
            side_effect=[
                ProcessingJobStatus.QUEUED,
                ProcessingJobStatus.QUEUED,
            ]
        )
        with (
            patch(
                "app.infrastructure.processing.delivery_watchdog.asyncio.sleep",
                new=AsyncMock(),
            ),
            patch(
                "app.infrastructure.processing.delivery_watchdog._queued_job_status",
                new=queued_status,
            ),
            patch(
                "app.infrastructure.processing.delivery_watchdog._worker_available",
                new=AsyncMock(return_value=False),
            ),
            patch(
                "app.infrastructure.processing.delivery_watchdog._run_locally",
                new=AsyncMock(),
            ) as run_locally,
            patch(
                "app.infrastructure.processing.delivery_watchdog._redeliver_to_worker",
                new=AsyncMock(),
            ) as redeliver,
        ):
            await run_passport_processing_job_watchdog(
                job_id="00000000-0000-0000-0000-000000000001",
                submission_id="00000000-0000-0000-0000-000000000002",
                delay_seconds=8.0,
                ping_timeout_seconds=1.0,
            )

        run_locally.assert_awaited_once()
        redeliver.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
