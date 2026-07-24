"""
Tests: Passport Confidence Scoring Service
=========================================
"""

from __future__ import annotations

from app.application.interfaces.passport_field_validator import (
    FieldValidationIssue,
    PassportFieldValidationResult,
)
from app.infrastructure.validation.passport_confidence_scoring_service import (
    PassportConfidenceScoringService,
)


class TestPassportConfidenceScoringService:
    def test_medium_confidence_without_image_quality_evidence(self) -> None:
        scorer = PassportConfidenceScoringService()
        result = scorer.score(
            extracted_fields={
                "surname": "DOE",
                "given_names": "JOHN",
                "passport_number": "A1234567",
                "nationality": "USA",
                "date_of_birth": "1990-01-01",
                "date_of_expiry": "2030-01-01",
                "sex": "M",
                "place_of_issue": "NEW YORK",
                "mrz_line_1": "P<USADOE<<JOHN<<<<<<<<<<<<<<<<<<<<<<",
                "mrz_line_2": "A1234567<0USA9001011M3001012<<<<<<<<<<<<<<04",
            },
            ocr_text="P<USADOE<<JOHN<<<<<<<<<<<<<<<<<<<<<<\nA1234567<0USA9001011M3001012<<<<<<<<<<<<<<04",
            mrz_raw="P<USADOE<<JOHN<<<<<<<<<<<<<<<<<<<<<<\nA1234567<0USA9001011M3001012<<<<<<<<<<<<<<04",
            validation=PassportFieldValidationResult(status="valid", issues=[]),
        )

        assert result.level == "medium"
        assert result.requires_manual_review is False
        assert result.overall >= 0.75
        assert result.to_dict()["signals"][0]["name"] == "field_completeness"

    def test_low_confidence_when_required_fields_are_missing(self) -> None:
        scorer = PassportConfidenceScoringService()
        result = scorer.score(
            extracted_fields={"surname": "DOE"},
            ocr_text=None,
            mrz_raw=None,
            validation=PassportFieldValidationResult(
                status="review_required",
                issues=[
                    FieldValidationIssue(
                        field="passport_number", message="Required field was not extracted."
                    )
                ],
            ),
        )

        assert result.level == "low"
        assert result.requires_manual_review is True
        assert any("Missing required fields" in reason for reason in result.review_reasons)
