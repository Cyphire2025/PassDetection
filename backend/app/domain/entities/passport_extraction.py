"""Revision-bound passport extraction and failure transitions."""

from __future__ import annotations

from app.domain.entities.enums import PassportExtractionStatus, PassportProcessingStatus
from app.domain.entities.factories import _utcnow
from app.domain.entities.passport_state import PassportSubmissionState
from app.domain.exceptions.exceptions import ValidationError
from app.domain.value_objects.passport_document_classification import (
    classification_outcome,
    manual_review_submission_allowed,
)
from app.domain.value_objects.passport_fields import (
    REVIEWABLE_PASSPORT_FIELDS,
    reconcile_confirmed_with_extraction,
)


class PassportExtraction(PassportSubmissionState):
    """Publish only revision-matched extraction results and failures."""

    def mark_processing(self) -> int:
        """Start a new extraction revision and return its immutable revision."""

        self.extraction_revision += 1
        self.extraction_status = PassportExtractionStatus.PROCESSING
        if self.status not in {
            PassportProcessingStatus.CLIENT_SUBMITTED,
            PassportProcessingStatus.CONFIRMED,
            PassportProcessingStatus.SUBMITTED,
            PassportProcessingStatus.AI_APPROVED,
            PassportProcessingStatus.NEEDS_REVIEW,
            PassportProcessingStatus.STAFF_APPROVED,
        }:
            self.status = PassportProcessingStatus.EXTRACTING
        self.error_message = None
        self.updated_at = _utcnow()
        return self.extraction_revision

    def ensure_reextract_allowed(self, *, source_image_replaced: bool = False) -> None:
        """Prevent extraction from mutating a pending or canonical approved row."""

        if self.status in {
            PassportProcessingStatus.SUBMITTED,
            PassportProcessingStatus.AI_APPROVED,
            PassportProcessingStatus.STAFF_APPROVED,
        }:
            raise ValidationError(
                "Re-extraction is unavailable while this passport is submitted or approved.",
                field="status",
            )
        if self.status == PassportProcessingStatus.NEEDS_REVIEW and not source_image_replaced:
            verification = self.post_submission_verification or {}
            raw_incorrect = verification.get("incorrect_fields")
            incorrect_fields = {
                field
                for field in (raw_incorrect if isinstance(raw_incorrect, list) else [])
                if isinstance(field, str) and field in REVIEWABLE_PASSPORT_FIELDS
            }
            if (
                verification.get("provider_status") != "verified"
                or verification.get("stale_after_staff_edit") is True
                or len(incorrect_fields) <= 3
            ):
                raise ValidationError(
                    "Re-extraction requires completed AI verification with more than three incorrect fields.",
                    field="post_submission_verification",
                )

    def mark_review_required(
        self,
        extracted_fields: dict[str, object],
        confidence: float,
        confidence_score: dict[str, object] | None = None,
        mrz_raw: str | None = None,
        *,
        expected_revision: int | None = None,
        review_threshold: float = 0.85,
    ) -> bool:
        if expected_revision is not None and expected_revision != self.extraction_revision:
            return False
        # Excel imports are an authoritative source. OCR can enrich blank
        # imported fields but must never replace them (or make an imported row
        # disappear from normal group views while it is being reprocessed).
        preserve_submitted_status = self.status in {
            PassportProcessingStatus.CLIENT_SUBMITTED,
            PassportProcessingStatus.CONFIRMED,
            PassportProcessingStatus.SUBMITTED,
            PassportProcessingStatus.AI_APPROVED,
            PassportProcessingStatus.NEEDS_REVIEW,
            PassportProcessingStatus.STAFF_APPROVED,
        }
        if not preserve_submitted_status:
            self.status = PassportProcessingStatus.READY_FOR_CLIENT_REVIEW
        required_fields = (
            "passport_number",
            "surname",
            "given_names",
            "date_of_birth",
            "date_of_expiry",
        )
        raw_verification = extracted_fields.get("ai_verification")
        raw_absent_fields = (
            raw_verification.get("absent_fields") if isinstance(raw_verification, dict) else None
        )
        absent_fields = {
            field
            for field in (raw_absent_fields if isinstance(raw_absent_fields, list) else [])
            if field == "surname"
        }
        required_fields_present = all(
            extracted_fields.get(key) or key in absent_fields for key in required_fields
        )
        manual_review_required = confidence < review_threshold
        self.extraction_status = (
            PassportExtractionStatus.READY_FOR_REVIEW
            if manual_review_required
            else (
                PassportExtractionStatus.COMPLETE
                if required_fields_present
                else PassportExtractionStatus.PARTIAL
            )
        )
        self.extracted_fields = extracted_fields
        self.confirmed_fields, self.extraction_conflicts = reconcile_confirmed_with_extraction(
            self.confirmed_fields,
            extracted_fields,
        )
        self.overall_confidence = confidence
        self.confidence_score = {
            **(confidence_score or {}),
            "review_policy": {
                "threshold": review_threshold,
                "manual_review_required": manual_review_required,
            },
        }
        self.mrz_raw = mrz_raw
        self.error_message = None
        if self.status == PassportProcessingStatus.NEEDS_REVIEW and self.confirmed_fields:
            # Re-reading the image must also compare every submitted field again.
            # Keep the traveller's values and fresh extraction conflicts available
            # for review; never treat an extraction result as approval by itself.
            self.post_submission_verification_revision += 1
            self.post_submission_verification = None
            self.post_submission_verified_at = None
            self.status = PassportProcessingStatus.SUBMITTED
        self.updated_at = _utcnow()
        return True

    def prepare_without_passport_front(self) -> None:
        """Make a configured details-only draft reviewable without an extraction job."""
        if self.image_s3_key:
            raise ValidationError(
                "A saved passport page must pass document verification.", field="file"
            )
        self.status = PassportProcessingStatus.READY_FOR_CLIENT_REVIEW
        self.extraction_status = PassportExtractionStatus.READY_FOR_REVIEW
        self.updated_at = _utcnow()

    def mark_no_passport_verification_required(self) -> None:
        """Retain an honest staff-review state when no identity page was collected."""
        if self.image_s3_key:
            raise ValidationError(
                "A saved passport page must pass document verification.", field="file"
            )
        self.status = PassportProcessingStatus.NEEDS_REVIEW
        self.extraction_status = PassportExtractionStatus.READY_FOR_REVIEW
        self.post_submission_verification = {
            "verification_status": "needs_review",
            "confidence": 0.0,
            "explanation": "No passport personal details page was collected for this submission.",
            "provider_status": "not_applicable",
            "reason_code": "PASSPORT_NOT_COLLECTED",
            "incorrect_fields": [],
            "suspicious_fields": [],
            "fields": [],
        }
        self.post_submission_verified_at = None
        self.updated_at = _utcnow()

    def restore_legacy_provider_failure_evidence(
        self,
        *,
        processing_job_revision: int,
        processing_job_status: str,
    ) -> None:
        """Upgrade legacy diagnostics only using a matching terminal server job."""
        if not manual_review_submission_allowed(
            extracted_fields=self.extracted_fields,
            extraction_revision=self.extraction_revision,
            extraction_status=self.extraction_status.value,
            status=self.status.value,
            image_s3_key=self.image_s3_key,
            processing_job_revision=processing_job_revision,
            processing_job_status=processing_job_status,
        ):
            return
        fields = dict(self.extracted_fields or {})
        classification = fields.get("ai_verification")
        if isinstance(classification, dict):
            fields["ai_verification"] = {
                **classification,
                **classification_outcome(
                    classification, extraction_revision=self.extraction_revision
                ),
            }
            self.extracted_fields = fields

    def mark_failed(self, reason: str) -> None:
        self.status = PassportProcessingStatus.FAILED
        self.extraction_status = PassportExtractionStatus.FAILED
        self.error_message = reason
        self.updated_at = _utcnow()

    def mark_extraction_failed(
        self,
        public_message: str = (
            "Some passport fields could not be read automatically. "
            "Please enter the missing details manually."
        ),
        *,
        expected_revision: int | None = None,
        diagnostics: dict[str, object] | None = None,
    ) -> bool:
        """Keep stored images reviewable after extraction failure."""

        if expected_revision is not None and expected_revision != self.extraction_revision:
            return False
        if self.status not in {
            PassportProcessingStatus.CLIENT_SUBMITTED,
            PassportProcessingStatus.CONFIRMED,
            PassportProcessingStatus.SUBMITTED,
            PassportProcessingStatus.AI_APPROVED,
            PassportProcessingStatus.NEEDS_REVIEW,
            PassportProcessingStatus.STAFF_APPROVED,
        }:
            self.status = PassportProcessingStatus.READY_FOR_CLIENT_REVIEW
        self.extraction_status = PassportExtractionStatus.FAILED
        self.error_message = public_message
        if diagnostics:
            self.extracted_fields = {
                **dict(self.extracted_fields or {}),
                **dict(diagnostics),
            }
        self.updated_at = _utcnow()
        return True
