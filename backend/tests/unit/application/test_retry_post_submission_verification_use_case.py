"""Focused tests for staff-triggered post-submission AI retry."""

from __future__ import annotations

import unittest
import uuid
from unittest.mock import AsyncMock

from app.application.use_cases.passports.retry_post_submission_verification_use_case import (
    RetryPostSubmissionVerificationUseCase,
)
from app.domain.entities.entities import PassportSubmission
from app.domain.exceptions.exceptions import ValidationError


def _failed_verification_submission(
    *,
    provider_status: str = "provider_unavailable",
) -> PassportSubmission:
    submission = PassportSubmission.create(
        group_id=uuid.uuid4(),
        agency_id=uuid.uuid4(),
        client_name="Traveller",
        client_email=None,
        image_s3_key="agency/group/passport.jpg",
    )
    submission.submit_client_review(
        {
            "surname": "VASISTHA",
            "given_names": "YOGESH KUMARK",
            "passport_number": "Z7418523",
        },
        client_email="traveller@example.com",
        client_phone=None,
    )
    submission.apply_post_submission_verification(
        expected_revision=submission.post_submission_verification_revision,
        decision="needs_review",
        verification={
            "verification_status": "needs_review",
            "provider_status": provider_status,
            "reason_code": "provider_unavailable",
        },
    )
    return submission


class RetryPostSubmissionVerificationUseCaseTests(
    unittest.IsolatedAsyncioTestCase
):
    async def test_requeues_new_revision_and_preserves_submitted_fields(self) -> None:
        submission = _failed_verification_submission()
        original_fields = dict(submission.confirmed_fields or {})
        original_revision = submission.post_submission_verification_revision
        repository = AsyncMock()
        repository.get_by_id_for_update.return_value = submission
        use_case = RetryPostSubmissionVerificationUseCase(repository)

        result = await use_case.execute(submission.id)

        self.assertEqual(result.previous_provider_status, "provider_unavailable")
        self.assertEqual(result.previous_reason_code, "provider_unavailable")
        self.assertEqual(result.submission.status, "submitted")
        self.assertEqual(
            result.submission.post_submission_verification_revision,
            original_revision + 1,
        )
        self.assertEqual(result.submission.confirmed_fields, original_fields)
        repository.update.assert_awaited_once_with(submission)

    async def test_does_not_update_a_genuine_ai_review(self) -> None:
        submission = _failed_verification_submission(provider_status="verified")
        repository = AsyncMock()
        repository.get_by_id_for_update.return_value = submission
        use_case = RetryPostSubmissionVerificationUseCase(repository)

        with self.assertRaises(ValidationError):
            await use_case.execute(submission.id)

        repository.update.assert_not_awaited()
