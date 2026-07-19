from __future__ import annotations

import unittest
import uuid

from app.domain.entities.entities import PassportProcessingStatus, PassportSubmission
from app.domain.value_objects.passport_fields import (
    reconcile_confirmed_with_extraction,
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
                "issuing_country": "India",
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
                "issuing_country": "IND",
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
        self.assertEqual(submission.confirmed_fields["issuing_country"], "India")
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


if __name__ == "__main__":
    unittest.main()
