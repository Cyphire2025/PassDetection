"""Domain invariants for the post-client-submit verification workflow."""

from __future__ import annotations

import asyncio
import unittest
import uuid
from unittest.mock import AsyncMock

from app.application.use_cases.passports.staff_approve_passport_use_case import (
    StaffApprovePassportUseCase,
    normalize_staff_review_reason,
)
from app.domain.entities.entities import (
    PassportProcessingStatus,
    PassportSubmission,
    StaffApprovalOutcome,
)
from app.domain.exceptions.exceptions import (
    StaffApprovalStaleError,
    StaffApprovalUnavailableError,
    ValidationError,
)
from app.domain.value_objects.passport_fields import (
    validate_reviewed_passport_payload,
)


def _submission() -> PassportSubmission:
    submission = PassportSubmission.create(
        group_id=uuid.uuid4(),
        agency_id=uuid.uuid4(),
        client_name="Traveller",
        client_email=None,
        image_s3_key="agency/group/passport.jpg",
    )
    submission.passport_back_s3_key = "agency/group/passport-back.jpg"
    return submission


def _reviewed_fields() -> dict[str, str]:
    return {
        "surname": "SHARMA",
        "given_names": "AMAN",
        "passport_number": "Z5292389",
        "nationality": "IND",
        "issuing_country": "India",
        "date_of_birth": "1990-01-02",
        "date_of_expiry": "2031-03-03",
        "sex": "M",
        "staff_code": "GC-7",
    }


def _reviewable_passport_fields() -> dict[str, str]:
    """Return only fields accepted from the untrusted staff-review request."""

    return {
        key: value
        for key, value in _reviewed_fields().items()
        if key != "staff_code"
    }


class PostSubmissionVerificationWorkflowTests(unittest.TestCase):
    def test_canonical_extraction_status_emissions(self) -> None:
        submission = _submission()
        self.assertEqual(
            submission.status,
            PassportProcessingStatus.PENDING_EXTRACTION,
        )
        revision = submission.mark_processing()
        self.assertEqual(submission.status, PassportProcessingStatus.EXTRACTING)
        submission.mark_review_required(
            _reviewed_fields(),
            0.95,
            expected_revision=revision,
        )
        self.assertEqual(
            submission.status,
            PassportProcessingStatus.READY_FOR_CLIENT_REVIEW,
        )

    def test_ai_result_never_changes_client_confirmed_fields(self) -> None:
        submission = _submission()
        fields = _reviewed_fields()
        submission.submit_client_review(
            fields,
            client_email="traveller@example.com",
            client_phone="+919999999999",
        )
        before = dict(submission.confirmed_fields or {})
        applied = submission.apply_post_submission_verification(
            expected_revision=submission.post_submission_verification_revision,
            decision="needs_review",
            verification={
                "verification_status": "needs_review",
                "incorrect_fields": ["passport_number"],
                "suspicious_fields": [],
            },
        )
        self.assertTrue(applied)
        self.assertEqual(submission.confirmed_fields, before)
        self.assertEqual(submission.status, PassportProcessingStatus.NEEDS_REVIEW)

    def test_client_submit_invalidates_an_inflight_extraction_revision(self) -> None:
        submission = _submission()
        stale_revision = submission.mark_processing()
        submission.submit_client_review(
            _reviewed_fields(),
            client_email="traveller@example.com",
            client_phone="+919999999999",
        )
        before = dict(submission.confirmed_fields or {})
        applied = submission.mark_review_required(
            {"passport_number": "ATTACKER-STALE"},
            1.0,
            expected_revision=stale_revision,
        )
        self.assertFalse(applied)
        self.assertEqual(submission.confirmed_fields, before)

    def test_staff_corrections_merge_metadata_and_approval_is_idempotent(self) -> None:
        submission = _submission()
        submission.submit_client_review(
            _reviewed_fields(),
            client_email="traveller@example.com",
            client_phone="+919999999999",
        )
        submission.apply_post_submission_verification(
            expected_revision=submission.post_submission_verification_revision,
            decision="needs_review",
            verification={"verification_status": "needs_review"},
        )
        reviewer_id = uuid.uuid4()
        outcome = submission.staff_approve_verification(
            reviewer_id=reviewer_id,
            reviewer_name="  Agency   Reviewer ",
            confirmed_fields={"passport_number": "Z5292390"},
            expected_extraction_revision=submission.extraction_revision,
        )
        self.assertEqual(outcome, StaffApprovalOutcome.APPROVED)
        self.assertEqual(
            submission.status,
            PassportProcessingStatus.STAFF_APPROVED,
        )
        self.assertEqual(
            submission.confirmed_fields["staff_code"],  # type: ignore[index]
            "GC-7",
        )
        self.assertEqual(
            submission.confirmed_fields["passport_number"],  # type: ignore[index]
            "Z5292390",
        )
        self.assertEqual(
            submission.verification_reviewed_by_user_id,
            reviewer_id,
        )
        self.assertEqual(submission.verification_reviewer_name, "Agency Reviewer")
        self.assertIsNotNone(submission.verification_reviewed_at)
        self.assertEqual(
            submission.staff_approve_verification(
                reviewer_id=reviewer_id,
                reviewer_name="Agency Reviewer",
                confirmed_fields={"passport_number": "Z5292390"},
                expected_extraction_revision=submission.extraction_revision,
            ),
            StaffApprovalOutcome.ALREADY_APPROVED,
        )
        with self.assertRaises(StaffApprovalUnavailableError):
            submission.staff_approve_verification(
                reviewer_id=reviewer_id,
                reviewer_name="Agency Reviewer",
                confirmed_fields={"passport_number": "SHOULD-NOT-APPLY"},
                expected_extraction_revision=submission.extraction_revision,
            )
        self.assertEqual(
            submission.confirmed_fields["passport_number"],  # type: ignore[index]
            "Z5292390",
        )

    def test_staff_decision_invalidates_late_ai_and_extraction_results(self) -> None:
        submission = _submission()
        extraction_revision = submission.mark_processing()
        submission.submit_client_review(
            _reviewed_fields(),
            client_email="traveller@example.com",
            client_phone="+919999999999",
        )
        ai_revision = submission.post_submission_verification_revision
        submission.apply_post_submission_verification(
            expected_revision=ai_revision,
            decision="needs_review",
            verification={"verification_status": "needs_review"},
        )
        current_extraction_revision = submission.extraction_revision

        outcome = submission.staff_approve_verification(
            reviewer_id=uuid.uuid4(),
            reviewer_name="Agency Reviewer",
            confirmed_fields={"passport_number": "Z5292390"},
            expected_extraction_revision=current_extraction_revision,
        )

        self.assertEqual(outcome, StaffApprovalOutcome.APPROVED)
        self.assertFalse(
            submission.apply_post_submission_verification(
                expected_revision=ai_revision,
                decision="ai_approved",
                verification={"verification_status": "ai_approved"},
            )
        )
        self.assertFalse(
            submission.mark_review_required(
                {"passport_number": "STALE-AI-VALUE"},
                1.0,
                expected_revision=extraction_revision,
            )
        )
        self.assertEqual(
            submission.status,
            PassportProcessingStatus.STAFF_APPROVED,
        )
        self.assertEqual(
            submission.confirmed_fields["passport_number"],  # type: ignore[index]
            "Z5292390",
        )

    def test_temporary_provider_failure_can_start_a_new_verification_revision(self) -> None:
        for provider_status in (
            "network_error",
            "provider_unavailable",
            "rate_limited",
            "timeout",
        ):
            with self.subTest(provider_status=provider_status):
                submission = _submission()
                fields = _reviewed_fields()
                submission.submit_client_review(
                    fields,
                    client_email="traveller@example.com",
                    client_phone="+919999999999",
                )
                previous_revision = submission.post_submission_verification_revision
                submission.apply_post_submission_verification(
                    expected_revision=previous_revision,
                    decision="needs_review",
                    verification={
                        "verification_status": "needs_review",
                        "provider_status": provider_status,
                        "reason_code": provider_status,
                    },
                )

                revision = submission.request_post_submission_verification_retry()

                self.assertEqual(revision, previous_revision + 1)
                self.assertEqual(
                    submission.status,
                    PassportProcessingStatus.SUBMITTED,
                )
                self.assertEqual(submission.confirmed_fields, fields)
                self.assertIsNone(submission.post_submission_verification)
                self.assertIsNone(submission.post_submission_verified_at)

    def test_genuine_ai_review_and_approved_states_cannot_be_retried(self) -> None:
        submission = _submission()
        submission.submit_client_review(
            _reviewed_fields(),
            client_email="traveller@example.com",
            client_phone="+919999999999",
        )
        submission.apply_post_submission_verification(
            expected_revision=submission.post_submission_verification_revision,
            decision="needs_review",
            verification={
                "verification_status": "needs_review",
                "provider_status": "verified",
                "incorrect_fields": ["given_names"],
            },
        )
        with self.assertRaises(ValidationError):
            submission.request_post_submission_verification_retry()

        for passport_status in (
            PassportProcessingStatus.SUBMITTED,
            PassportProcessingStatus.AI_APPROVED,
            PassportProcessingStatus.STAFF_APPROVED,
        ):
            with self.subTest(status=passport_status.value):
                submission.status = passport_status
                with self.assertRaises(ValidationError):
                    submission.request_post_submission_verification_retry()

    def test_already_office_visible_statuses_cannot_be_resubmitted(self) -> None:
        for passport_status in (
            PassportProcessingStatus.AI_APPROVED,
            PassportProcessingStatus.NEEDS_REVIEW,
            PassportProcessingStatus.STAFF_APPROVED,
        ):
            with self.subTest(status=passport_status.value):
                submission = _submission()
                submission.status = passport_status
                with self.assertRaises(ValidationError):
                    submission.submit_client_review(
                        _reviewed_fields(),
                        client_email="traveller@example.com",
                        client_phone="+919999999999",
                    )

    def test_reextract_is_blocked_while_submitted_or_canonically_approved(self) -> None:
        for passport_status in (
            PassportProcessingStatus.SUBMITTED,
            PassportProcessingStatus.AI_APPROVED,
            PassportProcessingStatus.STAFF_APPROVED,
        ):
            with self.subTest(status=passport_status.value):
                submission = _submission()
                submission.status = passport_status
                with self.assertRaises(ValidationError):
                    submission.ensure_reextract_allowed()

    def test_untrusted_review_payload_is_allowlisted_and_bounded(self) -> None:
        with self.assertRaisesRegex(
            ValidationError,
            "Unsupported reviewed passport field",
        ):
            validate_reviewed_passport_payload({"admin_override": "true"})
        with self.assertRaises(ValidationError):
            validate_reviewed_passport_payload({"surname": "A" * 161})


class StaffApprovePassportUseCaseTests(unittest.IsolatedAsyncioTestCase):
    async def test_nine_review_fields_preserve_existing_staff_metadata(self) -> None:
        submission = _submission()
        passport_fields = {
            "surname": "SHARMA",
            "given_names": "AMAN",
            "passport_number": "Z5292390",
            "nationality": "IND",
            "issuing_country": "India",
            "date_of_birth": "1990-01-02",
            "date_of_issue": "2021-03-04",
            "date_of_expiry": "2031-03-03",
            "sex": "M",
        }
        submission.submit_client_review(
            {
                **passport_fields,
                "passport_number": "Z5292389",
                "base_city": "Delhi",
                "staff_code": "GC-7",
                "meal_preference": "Vegetarian",
            },
            client_email="traveller@example.com",
            client_phone="+919999999999",
        )
        submission.apply_post_submission_verification(
            expected_revision=submission.post_submission_verification_revision,
            decision="needs_review",
            verification={"verification_status": "needs_review"},
        )
        repo = AsyncMock()
        repo.get_by_id_for_update.return_value = submission
        reviewer_id = uuid.uuid4()

        approval = await StaffApprovePassportUseCase(repo).execute(
            submission.id,
            reviewer_id=reviewer_id,
            reviewer_name="Agency Reviewer",
            confirmed_fields=passport_fields,
            expected_extraction_revision=submission.extraction_revision,
            review_reason="  Incorrect passport number confirmed.  ",
        )

        result = approval.submission
        self.assertEqual(approval.outcome, StaffApprovalOutcome.APPROVED)
        self.assertEqual(
            approval.corrected_field_names,
            ("passport_number",),
        )
        self.assertEqual(
            approval.review_reason,
            "Incorrect passport number confirmed.",
        )
        self.assertEqual(result.status, "staff_approved")
        self.assertEqual(result.confirmed_fields["base_city"], "Delhi")  # type: ignore[index]
        self.assertEqual(result.confirmed_fields["staff_code"], "GC-7")  # type: ignore[index]
        self.assertEqual(
            result.confirmed_fields["meal_preference"],  # type: ignore[index]
            "Vegetarian",
        )
        repo.update.assert_awaited_once_with(submission)

    async def test_identical_network_retry_is_idempotent(self) -> None:
        submission = _submission()
        fields = {
            "surname": "SHARMA",
            "given_names": "AMAN",
            "passport_number": "Z5292389",
            "nationality": "IND",
            "issuing_country": "India",
            "date_of_birth": "1990-01-02",
            "date_of_issue": "2021-03-04",
            "date_of_expiry": "2031-03-03",
            "sex": "M",
        }
        submission.submit_client_review(
            fields,
            client_email=None,
            client_phone=None,
        )
        submission.apply_post_submission_verification(
            expected_revision=submission.post_submission_verification_revision,
            decision="needs_review",
            verification={"verification_status": "needs_review"},
        )
        reviewer_id = uuid.uuid4()
        repo = AsyncMock()
        repo.get_by_id_for_update.return_value = submission
        use_case = StaffApprovePassportUseCase(repo)

        expected_revision = submission.extraction_revision
        first_approval = await use_case.execute(
            submission.id,
            reviewer_id=reviewer_id,
            reviewer_name="Agency Reviewer",
            confirmed_fields=fields,
            expected_extraction_revision=expected_revision,
        )
        second_approval = await use_case.execute(
            submission.id,
            reviewer_id=reviewer_id,
            reviewer_name="Agency Reviewer",
            confirmed_fields=fields,
            expected_extraction_revision=expected_revision,
        )

        self.assertEqual(first_approval.outcome, StaffApprovalOutcome.APPROVED)
        self.assertEqual(
            second_approval.outcome,
            StaffApprovalOutcome.ALREADY_APPROVED,
        )
        self.assertEqual(first_approval.submission.status, "staff_approved")
        self.assertEqual(second_approval.submission.status, "staff_approved")
        repo.update.assert_awaited_once_with(submission)

    async def test_stale_revision_returns_typed_conflict_without_mutation(self) -> None:
        submission = _submission()
        submission.submit_client_review(
            _reviewed_fields(),
            client_email=None,
            client_phone=None,
        )
        submission.apply_post_submission_verification(
            expected_revision=submission.post_submission_verification_revision,
            decision="needs_review",
            verification={"verification_status": "needs_review"},
        )
        repo = AsyncMock()
        repo.get_by_id_for_update.return_value = submission
        revision_before = submission.extraction_revision

        with self.assertRaises(StaffApprovalStaleError) as raised:
            await StaffApprovePassportUseCase(repo).execute(
                submission.id,
                reviewer_id=uuid.uuid4(),
                reviewer_name="Agency Reviewer",
                confirmed_fields=_reviewable_passport_fields(),
                expected_extraction_revision=revision_before - 1,
            )

        self.assertEqual(raised.exception.current_revision, revision_before)
        self.assertEqual(
            submission.status,
            PassportProcessingStatus.NEEDS_REVIEW,
        )
        repo.update.assert_not_awaited()

    async def test_non_review_workflow_states_are_typed_unavailable(self) -> None:
        for passport_status in (
            PassportProcessingStatus.SUBMITTED,
            PassportProcessingStatus.AI_APPROVED,
            PassportProcessingStatus.CONFIRMED,
            PassportProcessingStatus.FAILED,
        ):
            with self.subTest(status=passport_status.value):
                submission = _submission()
                submission.status = passport_status
                repo = AsyncMock()
                repo.get_by_id_for_update.return_value = submission

                with self.assertRaises(StaffApprovalUnavailableError) as raised:
                    await StaffApprovePassportUseCase(repo).execute(
                        submission.id,
                        reviewer_id=uuid.uuid4(),
                        reviewer_name="Agency Reviewer",
                        confirmed_fields=_reviewable_passport_fields(),
                        expected_extraction_revision=submission.extraction_revision,
                    )

                self.assertEqual(
                    raised.exception.current_status,
                    passport_status.value,
                )
                repo.update.assert_not_awaited()

    async def test_concurrent_same_approval_serializes_to_one_change(self) -> None:
        submission = _submission()
        fields = _reviewable_passport_fields()
        submission.submit_client_review(
            fields,
            client_email=None,
            client_phone=None,
        )
        submission.apply_post_submission_verification(
            expected_revision=submission.post_submission_verification_revision,
            decision="needs_review",
            verification={"verification_status": "needs_review"},
        )
        expected_revision = submission.extraction_revision

        class SerializingRepository:
            def __init__(self) -> None:
                self.lock = asyncio.Lock()
                self.update_count = 0

            async def get_by_id_for_update(self, _submission_id):  # type: ignore[no-untyped-def]
                async with self.lock:
                    await asyncio.sleep(0)
                    return submission

            async def update(self, _submission):  # type: ignore[no-untyped-def]
                self.update_count += 1
                await asyncio.sleep(0)

        repo = SerializingRepository()
        use_case = StaffApprovePassportUseCase(repo)  # type: ignore[arg-type]

        approvals = await asyncio.gather(
            *(
                use_case.execute(
                    submission.id,
                    reviewer_id=uuid.uuid4(),
                    reviewer_name=f"Reviewer {index}",
                    confirmed_fields=fields,
                    expected_extraction_revision=expected_revision,
                )
                for index in range(2)
            )
        )

        self.assertEqual(
            {approval.outcome for approval in approvals},
            {
                StaffApprovalOutcome.APPROVED,
                StaffApprovalOutcome.ALREADY_APPROVED,
            },
        )
        self.assertEqual(repo.update_count, 1)

    def test_review_reason_is_bounded_and_control_characters_are_removed(self) -> None:
        self.assertEqual(
            normalize_staff_review_reason("  Manual\nreview\u0000 completed.  "),
            "Manual review completed.",
        )
        with self.assertRaises(ValidationError):
            normalize_staff_review_reason("x" * 241)
