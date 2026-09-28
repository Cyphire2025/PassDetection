from __future__ import annotations

import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.domain.entities.entities import PassportProcessingStatus, PassportSubmission
from app.domain.exceptions.exceptions import ValidationError
from app.domain.value_objects.passport_fields import (
    REVIEWABLE_PASSPORT_FIELDS,
    reconcile_confirmed_with_extraction,
)
from app.infrastructure.repositories.passport_submission_repository import (
    PassportSubmissionRepository,
)


class PassportReextractionConflictTests(unittest.TestCase):
    def test_explicit_blank_surname_is_preserved_and_conflicts_with_new_value(
        self,
    ) -> None:
        merged, conflicts = reconcile_confirmed_with_extraction(
            {"surname": "", "given_names": "MOHIT"},
            {"surname": "MOHIT", "given_names": "MOHIT"},
        )

        self.assertEqual(merged["surname"], "")
        self.assertEqual(
            conflicts,
            [
                {
                    "field": "surname",
                    "manual_value": "",
                    "extracted_value": "MOHIT",
                    "status": "mismatch",
                }
            ],
        )

    def test_genuinely_missing_surname_key_is_still_filled(self) -> None:
        merged, conflicts = reconcile_confirmed_with_extraction(
            {"given_names": "AMAN"},
            {"surname": "SHARMA", "given_names": "AMAN"},
        )

        self.assertEqual(merged["surname"], "SHARMA")
        self.assertEqual(conflicts, [])

    def _manually_submitted_passport(self) -> PassportSubmission:
        submission = PassportSubmission.create(
            group_id=uuid.uuid4(),
            agency_id=uuid.uuid4(),
            client_name="Traveller",
            client_email=None,
            image_s3_key="agency/group/passport.jpg",
        )
        submission.submit_client_review(
            {
                "surname": "Kumar",
                "given_names": "Nipun",
                "passport_number": "a 1234567",
                "place_of_issue": "Chennai",
                "date_of_birth": "1990-01-01",
            },
            client_email="traveller@example.com",
            client_phone="9876543210",
        )
        return submission

    def test_reextraction_preserves_manual_values_fills_blanks_and_flags_conflicts(
        self,
    ) -> None:
        submission = self._manually_submitted_passport()
        revision = submission.mark_processing()

        applied = submission.mark_review_required(
            {
                "surname": "KUMAR",
                "given_names": "NIPIN",
                "passport_number": "A1234567",
                "place_of_issue": "CHENNAI",
                "date_of_expiry": "2031-02-03",
                "field_validation": {"status": "valid"},
                "ai_verification": {"status": "verified"},
            },
            confidence=0.96,
            expected_revision=revision,
        )

        self.assertTrue(applied)
        self.assertEqual(submission.status, PassportProcessingStatus.SUBMITTED)
        self.assertEqual(submission.confirmed_fields["surname"], "Kumar")
        self.assertEqual(submission.confirmed_fields["given_names"], "Nipun")
        self.assertEqual(submission.confirmed_fields["passport_number"], "a 1234567")
        self.assertEqual(submission.confirmed_fields["place_of_issue"], "Chennai")
        self.assertEqual(submission.confirmed_fields["date_of_expiry"], "2031-02-03")
        self.assertNotIn("field_validation", submission.confirmed_fields)
        self.assertNotIn("ai_verification", submission.confirmed_fields)
        self.assertEqual(
            submission.extraction_conflicts,
            [
                {
                    "field": "given_names",
                    "manual_value": "Nipun",
                    "extracted_value": "NIPIN",
                    "status": "mismatch",
                },
                {
                    "field": "date_of_birth",
                    "manual_value": "1990-01-01",
                    "extracted_value": None,
                    "status": "not_extracted",
                },
            ],
        )

    def test_legacy_issuing_country_is_preserved_without_masking_extracted_place(
        self,
    ) -> None:
        merged, conflicts = reconcile_confirmed_with_extraction(
            {"issuing_country": "India"},
            {"place_of_issue": "INDIA"},
        )

        assert merged is not None
        self.assertEqual(merged["place_of_issue"], "INDIA")
        self.assertEqual(merged["issuing_country"], "India")
        self.assertEqual(conflicts, [])

    def test_saving_manual_review_clears_resolved_conflicts(self) -> None:
        submission = self._manually_submitted_passport()
        submission.extraction_conflicts = [
            {
                "field": "given_names",
                "manual_value": "Nipun",
                "extracted_value": "NIPIN",
                "status": "mismatch",
            }
        ]

        submission.confirm(dict(submission.confirmed_fields or {}))

        self.assertEqual(submission.extraction_conflicts, [])

    def test_reextraction_of_reviewed_passport_starts_fresh_verification(self) -> None:
        submission = self._manually_submitted_passport()
        previous_revision = submission.post_submission_verification_revision
        submission.apply_post_submission_verification(
            expected_revision=previous_revision,
            decision="needs_review",
            verification={
                "provider_status": "verified",
                "incorrect_fields": list(REVIEWABLE_PASSPORT_FIELDS[:4]),
            },
        )
        submission.ensure_reextract_allowed()
        revision = submission.mark_processing()
        fresh_fields = {
            "surname": "KUMAR", "given_names": "NIPIN", "passport_number": "A1234567",
            "nationality": "IND", "place_of_issue": "CHENNAI", "date_of_birth": "1990-01-01",
            "date_of_issue": "2021-02-03", "date_of_expiry": "2031-02-03", "sex": "M",
        }

        self.assertTrue(submission.mark_review_required(
            fresh_fields, confidence=1.0, expected_revision=revision,
        ))

        self.assertEqual(submission.extracted_fields, fresh_fields)
        self.assertEqual(submission.confirmed_fields["given_names"], "Nipun")
        self.assertEqual(submission.status, PassportProcessingStatus.SUBMITTED)
        self.assertEqual(submission.post_submission_verification_revision, previous_revision + 1)
        self.assertIsNone(submission.post_submission_verification)
        self.assertIsNone(submission.post_submission_verified_at)
        self.assertFalse(submission.apply_post_submission_verification(
            expected_revision=previous_revision,
            decision="ai_approved", verification={"provider_status": "verified"},
        ))


@pytest.mark.parametrize("provider_status,incorrect_fields,allowed", [
    ("verified", list(REVIEWABLE_PASSPORT_FIELDS[:3]), False),
    ("verified", list(REVIEWABLE_PASSPORT_FIELDS[:4]), True),
    ("verified", ["surname"] * 4, False),
    ("verified", ["surname", "given_names", "passport_number", "unknown_field"], False),
    ("verified", None, False),
    ("timeout", list(REVIEWABLE_PASSPORT_FIELDS), False),
    ("manual_review_required", [], False),
])
def test_needs_review_reextract_requires_more_than_three_verified_incorrect_fields(
    provider_status, incorrect_fields, allowed,
):
    submission = PassportReextractionConflictTests()._manually_submitted_passport()
    submission.status = PassportProcessingStatus.NEEDS_REVIEW
    submission.post_submission_verification = {
        "provider_status": provider_status,
        "incorrect_fields": incorrect_fields,
        "suspicious_fields": list(REVIEWABLE_PASSPORT_FIELDS),
    }
    if allowed:
        submission.ensure_reextract_allowed()
    else:
        with pytest.raises(ValidationError, match="more than three incorrect fields"):
            submission.ensure_reextract_allowed()


async def test_reextraction_result_persists_new_verification_outbox_atomically():
    submission = PassportReextractionConflictTests()._manually_submitted_passport()
    submission.status = PassportProcessingStatus.NEEDS_REVIEW
    submission.post_submission_verification = {"provider_status": "verified"}
    previous_revision = submission.post_submission_verification_revision
    revision = submission.mark_processing()
    model = SimpleNamespace()
    session = AsyncMock()
    session.execute.return_value = SimpleNamespace(scalar_one_or_none=lambda: model)
    enqueue = AsyncMock()
    repository = PassportSubmissionRepository(session)

    with (
        patch.object(repository, "_to_entity", return_value=submission),
        patch(
            "app.infrastructure.repositories.passport_submission_repository.PostSubmissionVerificationJobRepository",
            return_value=SimpleNamespace(enqueue=enqueue),
        ),
    ):
        result = await repository.apply_extraction_result(
            submission_id=submission.id, expected_revision=revision,
            extracted_fields={"given_names": "NIPIN"}, confidence=1.0,
            confidence_score=None, mrz_raw=None,
        )

    assert result is submission
    assert model.status == "submitted"
    assert model.post_submission_verification is None
    assert model.post_submission_verification_revision == previous_revision + 1
    enqueue.assert_awaited_once_with(
        submission_id=submission.id, verification_revision=previous_revision + 1,
    )
    session.flush.assert_awaited_once()
    session.commit.assert_not_awaited()


def test_replacing_source_image_must_read_new_image_even_without_previous_field_errors():
    submission = PassportReextractionConflictTests()._manually_submitted_passport()
    submission.update_reviewed_fields({})
    assert submission.status == PassportProcessingStatus.NEEDS_REVIEW
    assert submission.post_submission_verification is None

    submission.ensure_reextract_allowed(source_image_replaced=True)

    with pytest.raises(ValidationError, match="more than three incorrect fields"):
        submission.ensure_reextract_allowed()


def test_stale_verification_cannot_authorize_reextract():
    submission = PassportReextractionConflictTests()._manually_submitted_passport()
    submission.status = PassportProcessingStatus.NEEDS_REVIEW
    submission.post_submission_verification = {
        "provider_status": "verified", "incorrect_fields": list(REVIEWABLE_PASSPORT_FIELDS),
        "stale_after_staff_edit": True,
    }
    with pytest.raises(ValidationError, match="more than three incorrect fields"):
        submission.ensure_reextract_allowed()


if __name__ == "__main__":
    unittest.main()
