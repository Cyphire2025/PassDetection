"""Runtime admission occurs before database claims or provider work."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from app.infrastructure.ai_priority.runtime import AiPriorityAdmissionDeferred
from app.infrastructure.ai_priority.state import (
    AdmissionDecision,
    AdmissionStatus,
    AiWorkload,
    PriorityLease,
    QueueCounts,
)
from app.infrastructure.processing.worker_runtime import run_passport_processing_job
from app.infrastructure.verification.runtime import (
    run_post_submission_verification,
)


class _Coordinator:
    def __init__(self, decision: AdmissionDecision) -> None:
        self.decision = decision
        self.released: list[PriorityLease] = []

    def try_start_extraction(self, job_reference: str) -> AdmissionDecision:
        return self.decision

    def try_start_verification(self, job_reference: str) -> AdmissionDecision:
        return self.decision

    def release(self, lease: PriorityLease) -> bool:
        self.released.append(lease)
        return True

    def heartbeat(self, lease: PriorityLease) -> bool:
        return True


def _decision(
    *,
    workload: AiWorkload,
    status: AdmissionStatus,
    reason: str,
) -> AdmissionDecision:
    return AdmissionDecision(
        status=status,
        reason=reason,
        lease=PriorityLease(
            workload=workload,
            job_key="a" * 64,
            generation=1,
            lease_ms=60_000,
        ),
        counts=QueueCounts(),
        retry_after_ms=25,
    )


class AiPriorityRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_extraction_admission_wraps_and_releases_runtime(self) -> None:
        coordinator = _Coordinator(
            _decision(
                workload=AiWorkload.EXTRACTION,
                status=AdmissionStatus.ADMITTED,
                reason="admitted",
            )
        )
        with patch(
            "app.infrastructure.processing.worker_runtime."
            "_run_passport_processing_job_admitted",
            new_callable=AsyncMock,
        ) as admitted:
            await run_passport_processing_job(
                job_id="00000000-0000-0000-0000-000000000001",
                submission_id="00000000-0000-0000-0000-000000000002",
                priority_coordinator=coordinator,  # type: ignore[arg-type]
            )
        admitted.assert_awaited_once()
        self.assertEqual(coordinator.released, [coordinator.decision.lease])

    async def test_extraction_capacity_deferral_precedes_runtime(self) -> None:
        coordinator = _Coordinator(
            _decision(
                workload=AiWorkload.EXTRACTION,
                status=AdmissionStatus.DEFERRED,
                reason="deferred_capacity",
            )
        )
        with patch(
            "app.infrastructure.processing.worker_runtime."
            "_run_passport_processing_job_admitted",
            new_callable=AsyncMock,
        ) as admitted:
            with self.assertRaises(AiPriorityAdmissionDeferred):
                await run_passport_processing_job(
                    job_id="00000000-0000-0000-0000-000000000001",
                    submission_id="00000000-0000-0000-0000-000000000002",
                    priority_coordinator=coordinator,  # type: ignore[arg-type]
                )
        admitted.assert_not_awaited()
        self.assertEqual(coordinator.released, [])

    async def test_duplicate_extraction_delivery_is_deferred_for_redelivery(
        self,
    ) -> None:
        coordinator = _Coordinator(
            _decision(
                workload=AiWorkload.EXTRACTION,
                status=AdmissionStatus.DUPLICATE,
                reason="duplicate_active",
            )
        )
        with patch(
            "app.infrastructure.processing.worker_runtime."
            "_run_passport_processing_job_admitted",
            new_callable=AsyncMock,
        ) as admitted:
            with self.assertRaises(AiPriorityAdmissionDeferred) as raised:
                await run_passport_processing_job(
                    job_id="00000000-0000-0000-0000-000000000001",
                    submission_id="00000000-0000-0000-0000-000000000002",
                    priority_coordinator=coordinator,  # type: ignore[arg-type]
                )
        admitted.assert_not_awaited()
        self.assertEqual(raised.exception.reason, "duplicate_active")
        self.assertEqual(raised.exception.retry_after_ms, 25)
        self.assertEqual(coordinator.released, [])

    async def test_duplicate_verification_delivery_is_deferred_for_redelivery(
        self,
    ) -> None:
        coordinator = _Coordinator(
            _decision(
                workload=AiWorkload.VERIFICATION,
                status=AdmissionStatus.DUPLICATE,
                reason="duplicate_active",
            )
        )
        with patch(
            "app.infrastructure.verification.runtime."
            "_run_post_submission_verification_admitted",
            new_callable=AsyncMock,
        ) as admitted:
            with self.assertRaises(AiPriorityAdmissionDeferred) as raised:
                await run_post_submission_verification(
                    job_id="00000000-0000-0000-0000-000000000001",
                    submission_id="00000000-0000-0000-0000-000000000002",
                    verification_revision=1,
                    priority_coordinator=coordinator,  # type: ignore[arg-type]
                )
        admitted.assert_not_awaited()
        self.assertEqual(raised.exception.reason, "duplicate_active")
        self.assertEqual(raised.exception.retry_after_ms, 25)
        self.assertEqual(coordinator.released, [])

    async def test_verification_fail_closed_precedes_database_claim(self) -> None:
        coordinator = _Coordinator(
            _decision(
                workload=AiWorkload.VERIFICATION,
                status=AdmissionStatus.DEFERRED,
                reason="redis_unavailable_fail_closed",
            )
        )
        with patch(
            "app.infrastructure.verification.runtime."
            "_run_post_submission_verification_admitted",
            new_callable=AsyncMock,
        ) as admitted:
            with self.assertRaises(AiPriorityAdmissionDeferred):
                await run_post_submission_verification(
                    job_id="00000000-0000-0000-0000-000000000001",
                    submission_id="00000000-0000-0000-0000-000000000002",
                    verification_revision=1,
                    priority_coordinator=coordinator,  # type: ignore[arg-type]
                )
        admitted.assert_not_awaited()

    async def test_active_verification_releases_after_provider_error(self) -> None:
        coordinator = _Coordinator(
            _decision(
                workload=AiWorkload.VERIFICATION,
                status=AdmissionStatus.ADMITTED,
                reason="admitted",
            )
        )
        with patch(
            "app.infrastructure.verification.runtime."
            "_run_post_submission_verification_admitted",
            new_callable=AsyncMock,
            side_effect=RuntimeError("provider failed"),
        ):
            with self.assertRaisesRegex(RuntimeError, "provider failed"):
                await run_post_submission_verification(
                    job_id="00000000-0000-0000-0000-000000000001",
                    submission_id="00000000-0000-0000-0000-000000000002",
                    verification_revision=1,
                    priority_coordinator=coordinator,  # type: ignore[arg-type]
                )
        self.assertEqual(coordinator.released, [coordinator.decision.lease])


if __name__ == "__main__":
    unittest.main()
