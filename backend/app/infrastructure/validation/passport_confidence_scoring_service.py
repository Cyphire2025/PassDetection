"""
Passport Confidence Scoring Service
==================================
Combines independent extraction signals into a transparent confidence score.
"""

from __future__ import annotations

from typing import Any

from app.application.interfaces.confidence_scoring import (
    ConfidenceSignal,
    IPassportConfidenceScoringService,
    PassportConfidenceScore,
)
from app.application.interfaces.passport_field_validator import PassportFieldValidationResult


class PassportConfidenceScoringService(IPassportConfidenceScoringService):
    """Rule-based scoring engine for passport OCR/MRZ extraction quality."""

    REQUIRED_FIELDS = (
        "surname",
        "given_names",
        "passport_number",
        "nationality",
        "date_of_birth",
        "date_of_expiry",
        "sex",
    )

    IMPORTANT_FIELDS = (
        "issuing_country",
        "personal_number",
        "mrz_line_1",
        "mrz_line_2",
    )

    def score(
        self,
        *,
        extracted_fields: dict[str, Any],
        ocr_text: str | None,
        mrz_raw: str | None,
        validation: PassportFieldValidationResult,
        evidence: dict[str, Any] | None = None,
        image_quality: float | None = None,
        fallback_used: bool = False,
    ) -> PassportConfidenceScore:
        signals = [
            self._field_completeness_signal(extracted_fields),
            self._mrz_integrity_signal(extracted_fields, mrz_raw),
            self._validation_signal(validation),
            self._ocr_support_signal(ocr_text),
            self._agreement_signal(evidence),
            self._engine_agreement_signal(evidence),
            self._image_quality_signal(image_quality),
            self._template_consistency_signal(extracted_fields),
            self._country_rules_signal(extracted_fields),
        ]
        weighted_total = sum(signal.score * signal.weight for signal in signals)
        total_weight = sum(signal.weight for signal in signals)
        fallback_penalty = 0.06 if fallback_used else 0.0
        overall = round(max(0.0, min(0.99, (weighted_total / total_weight) - fallback_penalty)), 3)
        review_reasons = self._review_reasons(extracted_fields, validation, overall)
        field_confidence = self._field_confidence(extracted_fields, evidence, validation)
        return PassportConfidenceScore(
            overall=overall,
            level=self._level(overall),
            signals=signals,
            requires_manual_review=bool(review_reasons),
            review_reasons=review_reasons,
            field_confidence=field_confidence,
            explanation={
                "fallback_used": fallback_used,
                "fallback_penalty": fallback_penalty,
                "signal_count": len(signals),
                "model": "weighted_signal_v2",
            },
        )

    def _field_completeness_signal(self, fields: dict[str, Any]) -> ConfidenceSignal:
        required_hits = sum(1 for field in self.REQUIRED_FIELDS if self._has_value(fields.get(field)))
        important_hits = sum(1 for field in self.IMPORTANT_FIELDS if self._has_value(fields.get(field)))
        score = ((required_hits / len(self.REQUIRED_FIELDS)) * 0.8) + (
            (important_hits / len(self.IMPORTANT_FIELDS)) * 0.2
        )
        return ConfidenceSignal(
            name="field_completeness",
            score=round(score, 3),
            weight=0.25,
            details={
                "required_present": required_hits,
                "required_total": len(self.REQUIRED_FIELDS),
                "important_present": important_hits,
                "important_total": len(self.IMPORTANT_FIELDS),
            },
        )

    def _mrz_integrity_signal(self, fields: dict[str, Any], mrz_raw: str | None) -> ConfidenceSignal:
        has_mrz_lines = self._has_value(fields.get("mrz_line_1")) and self._has_value(fields.get("mrz_line_2"))
        has_raw_mrz = self._has_value(mrz_raw)
        score = 1.0 if has_mrz_lines else 0.65 if has_raw_mrz else 0.25
        return ConfidenceSignal(
            name="mrz_integrity",
            score=score,
            weight=0.2,
            details={
                "has_raw_mrz": has_raw_mrz,
                "has_mrz_line_1": self._has_value(fields.get("mrz_line_1")),
                "has_mrz_line_2": self._has_value(fields.get("mrz_line_2")),
            },
        )

    def _validation_signal(self, validation: PassportFieldValidationResult) -> ConfidenceSignal:
        error_count = sum(1 for issue in validation.issues if issue.severity == "error")
        warning_count = len(validation.issues) - error_count
        penalty = (error_count * 0.25) + (warning_count * 0.08)
        score = round(max(0.0, 1.0 - penalty), 3)
        return ConfidenceSignal(
            name="field_validation",
            score=score,
            weight=0.15,
            details={
                "status": validation.status,
                "error_count": error_count,
                "warning_count": warning_count,
            },
        )

    def _ocr_support_signal(self, ocr_text: str | None) -> ConfidenceSignal:
        text_length = len(ocr_text or "")
        if text_length >= 120:
            score = 0.85
        elif text_length >= 40:
            score = 0.65
        elif text_length > 0:
            score = 0.4
        else:
            score = 0.2
        return ConfidenceSignal(
            name="ocr_support",
            score=score,
            weight=0.05,
            details={"text_length": text_length},
        )

    def _agreement_signal(self, evidence: dict[str, Any] | None) -> ConfidenceSignal:
        agreements = [
            float(item.get("agreement", 0.0))
            for item in (evidence or {}).values()
            if isinstance(item, dict)
        ]
        score = sum(agreements) / len(agreements) if agreements else 0.75
        return ConfidenceSignal(
            name="ocr_agreement",
            score=round(score, 3),
            weight=0.15,
            details={"fields_evaluated": len(agreements)},
        )

    def _engine_agreement_signal(self, evidence: dict[str, Any] | None) -> ConfidenceSignal:
        engine_counts: list[int] = []
        for item in (evidence or {}).values():
            if not isinstance(item, dict):
                continue
            supporting = item.get("supporting_evidence", [])
            engines = {
                support.get("ocr_engine")
                for support in supporting
                if isinstance(support, dict) and support.get("ocr_engine")
            }
            engine_counts.append(len(engines))
        if not engine_counts:
            score = 0.75
        else:
            score = sum(min(1.0, count / 2) for count in engine_counts) / len(engine_counts)
        return ConfidenceSignal(
            name="engine_agreement",
            score=round(score, 3),
            weight=0.1,
            details={"fields_evaluated": len(engine_counts)},
        )

    def _image_quality_signal(self, image_quality: float | None) -> ConfidenceSignal:
        score = 0.8 if image_quality is None else max(0.0, min(1.0, image_quality))
        return ConfidenceSignal(
            name="image_quality",
            score=round(score, 3),
            weight=0.05,
            details={"measured": image_quality is not None},
        )

    def _template_consistency_signal(self, fields: dict[str, Any]) -> ConfidenceSignal:
        has_td3 = len(str(fields.get("mrz_line_1", ""))) == 44 and len(
            str(fields.get("mrz_line_2", ""))
        ) == 44
        score = 1.0 if has_td3 else 0.7
        return ConfidenceSignal(
            name="passport_template_consistency",
            score=score,
            weight=0.025,
            details={"td3_shape_valid": has_td3},
        )

    def _country_rules_signal(self, fields: dict[str, Any]) -> ConfidenceSignal:
        nationality = str(fields.get("nationality", ""))
        issuing_country = str(fields.get("issuing_country", ""))
        valid_codes = all(
            len(value) == 3 and value.isalpha()
            for value in (nationality, issuing_country)
            if value
        )
        score = 1.0 if valid_codes and nationality else 0.7
        return ConfidenceSignal(
            name="country_rule_validation",
            score=score,
            weight=0.025,
            details={"nationality": nationality, "issuing_country": issuing_country},
        )

    def _field_confidence(
        self,
        fields: dict[str, Any],
        evidence: dict[str, Any] | None,
        validation: PassportFieldValidationResult,
    ) -> dict[str, float]:
        issue_fields = {issue.field for issue in validation.issues}
        result: dict[str, float] = {}
        for field_name in (*self.REQUIRED_FIELDS, *self.IMPORTANT_FIELDS):
            if not self._has_value(fields.get(field_name)):
                continue
            evidence_item = (evidence or {}).get(field_name, {})
            base = float(evidence_item.get("confidence", 0.72))
            if field_name in issue_fields:
                base -= 0.2
            result[field_name] = round(max(0.0, min(0.99, base)), 3)
        return result

    def _review_reasons(
        self,
        fields: dict[str, Any],
        validation: PassportFieldValidationResult,
        overall: float,
    ) -> list[str]:
        reasons: list[str] = []
        missing_fields = [field for field in self.REQUIRED_FIELDS if not self._has_value(fields.get(field))]
        if missing_fields:
            reasons.append(f"Missing required fields: {', '.join(missing_fields)}")
        if validation.issues:
            reasons.append("One or more extracted fields failed deterministic validation.")
        if overall < 0.75:
            reasons.append("Overall confidence is below the automatic acceptance threshold.")
        return reasons

    def _level(self, score: float) -> str:
        if score >= 0.9:
            return "high"
        if score >= 0.75:
            return "medium"
        return "low"

    def _has_value(self, value: Any) -> bool:
        return isinstance(value, str) and bool(value.strip())
