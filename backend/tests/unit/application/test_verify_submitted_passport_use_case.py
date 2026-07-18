"""Retry semantics for the durable post-submit verification use case."""

from __future__ import annotations

import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.application.interfaces.post_submission_verification import (
    PostSubmissionVerificationResult,
)
from app.application.use_cases.passports.verify_submitted_passport_use_case import (
    VerifySubmittedPassportUseCase,
)
from app.domain.entities.entities import PassportSubmission


def _submitted_passport() -> PassportSubmission:
    submission = PassportSubmission.create(
        group_id=uuid.uuid4(),
        agency_id=uuid.uuid4(),
        client_name="Traveller",
        client_email=None,
        image_s3_key="agency/group/passport.jpg",
    )
    submission.submit_client_review(
        {
            "surname": "VASHISTHA",
            "given_names": "YOGESH KUMARK",
            "passport_number": "Z7418523",
            "nationality": "IND",
            "issuing_country": "IND",
            "date_of_birth": "1972-08-30",
            "date_of_issue": "2023-08-10",
            "date_of_expiry": "2033-08-09",
            "sex": "M",
        },
        client_email="traveller@example.com",
        client_phone="+919999999999",
    )
    return submission


class VerifySubmittedPassportUseCaseTests(unittest.IsolatedAsyncioTestCase):
    async def test_exhausted_provider_attempts_persist_conservative_review_state(
        self,
    ) -> None:
        submission = _submitted_passport()
        passport_repo = SimpleNamespace(
            get_by_id=AsyncMock(return_value=submission),
            apply_post_submission_verification=AsyncMock(
                return_value=submission
            ),
        )
        storage_repo = SimpleNamespace(
            get_file=AsyncMock(return_value=b"passport-image")
        )
        transient = PostSubmissionVerificationResult.fallback(
            provider_status="provider_unavailable",
            reason_code="provider_unavailable",
            model="gemini-3.1-flash-lite",
            submitted_fields=dict(submission.confirmed_fields or {}),
        )
        verification_service = SimpleNamespace(
            verify=AsyncMock(return_value=transient)
        )
        use_case = VerifySubmittedPassportUseCase(
            passport_repo=passport_repo,
            storage_repo=storage_repo,
            verification_service=verification_service,
        )

        result = await use_case.execute(
            submission_id=submission.id,
            expected_revision=submission.post_submission_verification_revision,
        )

        self.assertIsNotNone(result)
        passport_repo.apply_post_submission_verification.assert_awaited_once_with(
            submission_id=submission.id,
            expected_revision=submission.post_submission_verification_revision,
            decision="needs_review",
            verification=transient.to_dict(),
        )
