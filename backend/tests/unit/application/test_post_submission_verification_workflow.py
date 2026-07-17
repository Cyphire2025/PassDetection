"""Domain invariants for the post-client-submit verification workflow."""

from __future__ import annotations

import unittest
import uuid

from app.domain.entities.entities import (
    PassportProcessingStatus,
    PassportSubmission,
)
from app.domain.exceptions.exceptions import ValidationError
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
        changed = submission.staff_approve_verification(
            reviewer_id=reviewer_id,
            reviewer_name="  Agency   Reviewer ",
            confirmed_fields={"passport_number": "Z5292390"},
        )
        self.assertTrue(changed)
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
        self.assertFalse(
            submission.staff_approve_verification(
                reviewer_id=reviewer_id,
                reviewer_name="Agency Reviewer",
                confirmed_fields={"passport_number": "Z5292390"},
            )
        )
        with self.assertRaises(ValidationError):
            submission.staff_approve_verification(
                reviewer_id=reviewer_id,
                reviewer_name="Agency Reviewer",
                confirmed_fields={"passport_number": "SHOULD-NOT-APPLY"},
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
        with self.assertRaises(ValidationError):
            validate_reviewed_passport_payload({"admin_override": "true"})
        with self.assertRaises(ValidationError):
            validate_reviewed_passport_payload({"surname": "A" * 161})
