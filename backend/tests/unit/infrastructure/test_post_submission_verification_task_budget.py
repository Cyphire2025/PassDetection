from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from celery.exceptions import MaxRetriesExceededError, Reject

from app.application.use_cases.passports.process_passport_submission_job_use_case import (
    ProcessingJobBusy,
    ProcessingRetryRequested,
)
from app.core.config.settings import get_settings
from app.infrastructure.ai_priority import AiPriorityAdmissionDeferred
from app.infrastructure.processing.tasks import process_passport_submission
from app.infrastructure.verification.tasks import verify_submitted_passport


def test_verification_delivery_retries_match_the_durable_crash_budget() -> None:
    settings = get_settings()

    assert verify_submitted_passport.max_retries == max(
        0,
        settings.processing_job_max_attempts - 1,
    )


def test_extraction_delivery_retries_match_the_durable_crash_budget() -> None:
    settings = get_settings()

    assert process_passport_submission.max_retries == max(
        0,
        settings.processing_job_max_attempts - 1,
    )


def _deferred(workload: str) -> AiPriorityAdmissionDeferred:
    return AiPriorityAdmissionDeferred(
        workload=workload,
        reason="duplicate_active",
        retry_after_ms=2_000,
    )


def test_extraction_requeues_current_delivery_when_redelivery_publish_fails(
) -> None:
    with (
        patch(
            "app.infrastructure.processing.tasks."
            "run_passport_processing_job",
            new=AsyncMock(side_effect=_deferred("extraction")),
        ),
        patch.object(
            process_passport_submission,
            "apply_async",
            side_effect=ConnectionError("broker publish failed"),
        ),
        pytest.raises(Reject) as raised,
    ):
        process_passport_submission.run(
            job_id="00000000-0000-0000-0000-000000000001",
            submission_id="00000000-0000-0000-0000-000000000002",
        )

    assert raised.value.requeue is True


def test_busy_running_fresh_redelivery_ignores_celery_retry_exhaustion(
) -> None:
    busy = ProcessingJobBusy(retry_after_ms=4_000)
    with (
        patch(
            "app.infrastructure.processing.tasks."
            "run_passport_processing_job",
            new=AsyncMock(side_effect=busy),
        ),
        patch.object(
            process_passport_submission,
            "apply_async",
        ) as redeliver,
        patch.object(process_passport_submission, "retry") as durable_retry,
    ):
        process_passport_submission.push_request(
            retries=process_passport_submission.max_retries
        )
        try:
            process_passport_submission.run(
                job_id="00000000-0000-0000-0000-000000000001",
                submission_id="00000000-0000-0000-0000-000000000002",
            )
        finally:
            process_passport_submission.pop_request()

    redeliver.assert_called_once_with(
        kwargs={
            "job_id": "00000000-0000-0000-0000-000000000001",
            "submission_id": "00000000-0000-0000-0000-000000000002",
        },
        queue="interactive-passport-extraction",
        countdown=4,
    )
    durable_retry.assert_not_called()


def test_busy_running_requeues_current_delivery_when_publish_fails() -> None:
    with (
        patch(
            "app.infrastructure.processing.tasks."
            "run_passport_processing_job",
            new=AsyncMock(side_effect=ProcessingJobBusy()),
        ),
        patch.object(
            process_passport_submission,
            "apply_async",
            side_effect=ConnectionError("broker publish failed"),
        ),
        pytest.raises(Reject) as raised,
    ):
        process_passport_submission.run(
            job_id="00000000-0000-0000-0000-000000000001",
            submission_id="00000000-0000-0000-0000-000000000002",
        )

    assert raised.value.requeue is True


def test_provider_retry_exhaustion_does_not_fresh_redeliver() -> None:
    with (
        patch(
            "app.infrastructure.processing.tasks."
            "run_passport_processing_job",
            new=AsyncMock(
                side_effect=ProcessingRetryRequested(
                    "provider retry requested"
                )
            ),
        ),
        patch.object(
            process_passport_submission,
            "retry",
            side_effect=MaxRetriesExceededError(),
        ) as durable_retry,
        patch.object(process_passport_submission, "apply_async") as redeliver,
        pytest.raises(MaxRetriesExceededError),
    ):
        process_passport_submission.run(
            job_id="00000000-0000-0000-0000-000000000001",
            submission_id="00000000-0000-0000-0000-000000000002",
        )

    durable_retry.assert_called_once()
    redeliver.assert_not_called()


def test_verification_requeues_current_delivery_when_redelivery_publish_fails(
) -> None:
    with (
        patch(
            "app.infrastructure.verification.tasks."
            "run_post_submission_verification",
            new=AsyncMock(side_effect=_deferred("verification")),
        ),
        patch.object(
            verify_submitted_passport,
            "apply_async",
            side_effect=ConnectionError("broker publish failed"),
        ),
        pytest.raises(Reject) as raised,
    ):
        verify_submitted_passport.run(
            job_id="00000000-0000-0000-0000-000000000001",
            submission_id="00000000-0000-0000-0000-000000000002",
            verification_revision=1,
        )

    assert raised.value.requeue is True
