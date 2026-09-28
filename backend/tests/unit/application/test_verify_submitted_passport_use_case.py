"""Retry semantics for the durable post-submit verification use case."""

from __future__ import annotations

import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.application.interfaces.post_submission_verification import (
    POST_SUBMISSION_PASSPORT_FIELDS,
    PostSubmissionFieldResult,
    PostSubmissionFieldVerdict,
    PostSubmissionVerificationDecision,
    PostSubmissionVerificationResult,
)
from app.application.use_cases.passports.verify_submitted_passport_use_case import (
    VerifySubmittedPassportUseCase,
)
from app.domain.entities.entities import PassportProcessingStatus, PassportSubmission


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
            "place_of_issue": "CHENNAI",
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
    async def test_canonical_place_of_issue_is_sent_for_verification(self) -> None:
        submission = _submitted_passport()
        passport_repo = SimpleNamespace(
            get_by_id=AsyncMock(return_value=submission),
            apply_post_submission_verification=AsyncMock(return_value=submission),
        )
        storage_repo = SimpleNamespace(get_file=AsyncMock(return_value=b"passport-image"))
        verification = PostSubmissionVerificationResult.fallback(
            provider_status="disabled",
            reason_code="verification_disabled",
        )
        verification_service = SimpleNamespace(verify=AsyncMock(return_value=verification))

        await VerifySubmittedPassportUseCase(
            passport_repo=passport_repo,
            storage_repo=storage_repo,
            verification_service=verification_service,
        ).execute(
            submission_id=submission.id,
            expected_revision=submission.post_submission_verification_revision,
        )

        submitted_fields = verification_service.verify.await_args.kwargs["submitted_fields"]
        self.assertEqual(set(submitted_fields), set(POST_SUBMISSION_PASSPORT_FIELDS))
        self.assertEqual(submitted_fields["place_of_issue"], "CHENNAI")
        self.assertNotIn("issuing_country", submitted_fields)

    async def test_legacy_issuing_country_is_not_sent_for_place_verification(
        self,
    ) -> None:
        submission = _submitted_passport()
        assert submission.confirmed_fields is not None
        submission.confirmed_fields.pop("place_of_issue")
        submission.confirmed_fields["issuing_country"] = "India"
        passport_repo = SimpleNamespace(
            get_by_id=AsyncMock(return_value=submission),
            apply_post_submission_verification=AsyncMock(return_value=submission),
        )
        storage_repo = SimpleNamespace(get_file=AsyncMock(return_value=b"passport-image"))
        verification = PostSubmissionVerificationResult.fallback(
            provider_status="disabled",
            reason_code="verification_disabled",
        )
        verification_service = SimpleNamespace(verify=AsyncMock(return_value=verification))

        await VerifySubmittedPassportUseCase(
            passport_repo=passport_repo,
            storage_repo=storage_repo,
            verification_service=verification_service,
        ).execute(
            submission_id=submission.id,
            expected_revision=submission.post_submission_verification_revision,
        )

        submitted_fields = verification_service.verify.await_args.kwargs["submitted_fields"]
        self.assertNotIn("place_of_issue", submitted_fields)
        self.assertNotIn("issuing_country", submitted_fields)

    async def test_exhausted_provider_attempts_persist_conservative_review_state(
        self,
    ) -> None:
        submission = _submitted_passport()
        passport_repo = SimpleNamespace(
            get_by_id=AsyncMock(return_value=submission),
            apply_post_submission_verification=AsyncMock(return_value=submission),
        )
        storage_repo = SimpleNamespace(get_file=AsyncMock(return_value=b"passport-image"))
        transient = PostSubmissionVerificationResult.fallback(
            provider_status="provider_unavailable",
            reason_code="provider_unavailable",
            model="gemini-3.1-flash-lite",
            submitted_fields=dict(submission.confirmed_fields or {}),
        )
        verification_service = SimpleNamespace(verify=AsyncMock(return_value=transient))
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

    async def test_manual_submission_is_verified_from_image_after_first_pass_failed(self) -> None:
        for incorrect_count in (0, 4):
            with self.subTest(incorrect_count=incorrect_count):
                submission = _submitted_passport()
                # Stored diagnostics from initial reading must not prevent a
                # separate verification of the subsequently typed values.
                submission.extracted_fields = {"ai_verification": {
                    "status": "timeout", "available": False,
                    "outcome_kind": "provider_failure", "extraction_revision": 1,
                }}
                revision = submission.post_submission_verification_revision
                values = dict(submission.confirmed_fields or {})
                verification = PostSubmissionVerificationResult(
                    decision=(
                        PostSubmissionVerificationDecision.NEEDS_REVIEW if incorrect_count
                        else PostSubmissionVerificationDecision.AI_APPROVED
                    ),
                    confidence=1.0,
                    explanation="Compared each field with the passport image.",
                    provider_status="verified", reason_code=None, model="test-model",
                    fields=tuple(
                        PostSubmissionFieldResult(
                            field=name,
                            verdict=(PostSubmissionFieldVerdict.INCORRECT if index < incorrect_count
                                     else PostSubmissionFieldVerdict.CORRECT),
                            observed_value=values[name], confidence=1.0, reason_code="match",
                        ) for index, name in enumerate(POST_SUBMISSION_PASSPORT_FIELDS)
                    ),
                )

                async def apply(**kwargs):
                    kwargs.pop("submission_id")
                    return submission if submission.apply_post_submission_verification(**kwargs) else None

                passport_repo = SimpleNamespace(
                    get_by_id=AsyncMock(return_value=submission),
                    apply_post_submission_verification=AsyncMock(side_effect=apply),
                )
                storage = SimpleNamespace(get_file=AsyncMock(return_value=b"saved-passport-image"))
                service = SimpleNamespace(verify=AsyncMock(return_value=verification))
                result = await VerifySubmittedPassportUseCase(
                    passport_repo=passport_repo, storage_repo=storage, verification_service=service,
                ).execute(submission_id=submission.id, expected_revision=revision)

                storage.get_file.assert_awaited_once_with(submission.image_s3_key)
                service.verify.assert_awaited_once_with(
                    b"saved-passport-image", content_type="image/jpeg", submitted_fields=values,
                )
                self.assertEqual(result.status, "needs_review" if incorrect_count else "ai_approved")
                self.assertEqual(len(result.post_submission_verification["fields"]), 9)
                self.assertEqual(len(result.post_submission_verification["incorrect_fields"]), incorrect_count)
                self.assertEqual(submission.confirmed_fields, values)
                self.assertNotEqual(submission.status, PassportProcessingStatus.SUBMITTED)
