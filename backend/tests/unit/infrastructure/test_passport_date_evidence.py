"""Tests for bounded passport vision date normalization."""

from __future__ import annotations

import unittest

from app.infrastructure.ai.passport_date_evidence import (
    normalize_passport_date_evidence,
    passport_date_evidence_candidates,
    passport_numeric_date_order_hint,
)


class PassportDateEvidenceTests(unittest.TestCase):
    def test_accepts_common_unambiguous_numeric_formats(self) -> None:
        for value in (
            "1972-08-30",
            "1972/08/30",
            "1972.08.30",
            "1972 08 30",
            "1972 / 08 / 30",
            "19720830",
            "30-08-1972",
            "30/08/1972",
            "30.08.1972",
            "30 08 1972",
            "30 / 08 / 1972",
            "30081972",
            "08/30/1972",
        ):
            with self.subTest(value=value):
                self.assertEqual(
                    normalize_passport_date_evidence(
                        value,
                        field="date_of_birth",
                    ),
                    "1972-08-30",
                )

    def test_accepts_common_named_month_formats(self) -> None:
        for value in (
            "30 AUG 1972",
            "30-AUG-1972",
            "30th August 1972",
            "August 30, 1972",
            "AUG 30 1972",
            "1972-AUG-30",
            "30AUG1972",
            "1972AUG30",
        ):
            with self.subTest(value=value):
                self.assertEqual(
                    normalize_passport_date_evidence(
                        value,
                        field="date_of_birth",
                    ),
                    "1972-08-30",
                )

    def test_rejects_ambiguous_or_unsafe_date_text(self) -> None:
        for value in (
            "03/04/1972",
            "03-04-1972",
            "03.04.1972",
            "03 04 1972",
            "03/04-1972",
            "72/08/30",
            "720830",
            "31/02/1972",
            "1972-02-30",
            "passport says 30/08/1972",
            "３０/０８/１９７２",
        ):
            with self.subTest(value=value):
                self.assertEqual(
                    normalize_passport_date_evidence(
                        value,
                        field="date_of_birth",
                    ),
                    "",
                )

    def test_surfaces_both_interpretations_for_ambiguous_numeric_dates(
        self,
    ) -> None:
        self.assertEqual(
            passport_date_evidence_candidates(
                "03/04/1972",
                field="date_of_birth",
            ),
            ("1972-04-03", "1972-03-04"),
        )

    def test_uses_only_unambiguous_document_order_hints(self) -> None:
        self.assertEqual(
            passport_numeric_date_order_hint("30/08/1972"),
            "day_first",
        )
        self.assertEqual(
            passport_numeric_date_order_hint("08/30/1972"),
            "month_first",
        )
        self.assertIsNone(passport_numeric_date_order_hint("03/04/1972"))
        self.assertEqual(
            normalize_passport_date_evidence(
                "09/08/2033",
                field="date_of_expiry",
                numeric_order="day_first",
            ),
            "2033-08-09",
        )
        self.assertEqual(
            normalize_passport_date_evidence(
                "08/09/2033",
                field="date_of_expiry",
                numeric_order="month_first",
            ),
            "2033-08-09",
        )

    def test_enforces_field_specific_date_bounds(self) -> None:
        self.assertEqual(
            normalize_passport_date_evidence(
                "2200-01-01",
                field="date_of_birth",
            ),
            "",
        )
        self.assertEqual(
            normalize_passport_date_evidence(
                "2200-01-01",
                field="date_of_issue",
            ),
            "",
        )
        self.assertEqual(
            normalize_passport_date_evidence(
                "2200-01-01",
                field="date_of_expiry",
            ),
            "2200-01-01",
        )


if __name__ == "__main__":
    unittest.main()
