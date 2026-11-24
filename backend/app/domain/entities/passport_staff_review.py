"""Revision-bound AI verification and canonical staff review transitions."""

from __future__ import annotations

import uuid

from app.domain.entities.enums import (
    RETRYABLE_POST_SUBMISSION_PROVIDER_STATUSES,
    PassportProcessingStatus,
    StaffApprovalOutcome,
)
from app.domain.entities.factories import _utcnow
from app.domain.entities.passport_state import PassportSubmissionState
from app.domain.exceptions.exceptions import (
    StaffApprovalStaleError,
    StaffApprovalUnavailableError,
    ValidationError,
)
from app.domain.value_objects.passport_document_classification import requires_manual_staff_review


class PassportStaffReview(PassportSubmissionState):
    """Apply current AI evidence and canonical staff decisions."""

    def apply_post_submission_verification(
        self,
        *,
        expected_revision: int,
        decision: str,
        verification: dict[str, object],
    ) -> bool:
        """Apply one revision-matched AI decision without changing client fields."""

        if (
            expected_revision != self.post_submission_verification_revision
            or self.status != PassportProcessingStatus.SUBMITTED
            or requires_manual_staff_review(self.post_submission_verification)
        ):
            return False
        if decision not in {
            PassportProcessingStatus.AI_APPROVED.value,
            PassportProcessingStatus.NEEDS_REVIEW.value,
        }:
            raise ValidationError("Unsupported post-submission verification decision.")

        now = _utcnow()
        self.status = PassportProcessingStatus(decision)
        self.post_submission_verification = dict(verification)
        self.post_submission_verified_at = now
        self.error_message = None
        self.updated_at = now
        return True

    def request_post_submission_verification_retry(self) -> int:
        """Retry a provider failure or verify a legacy manual fallback submission."""

        if self.status != PassportProcessingStatus.NEEDS_REVIEW:
            raise ValidationError(
                "AI verification can only be retried after a temporary provider failure.",
                field="status",
            )
        verification = self.post_submission_verification
        provider_status = (
            str(verification.get("provider_status", "")).strip().lower()
            if isinstance(verification, dict)
            else ""
        )
        if (
            provider_status not in RETRYABLE_POST_SUBMISSION_PROVIDER_STATUSES
            and not requires_manual_staff_review(verification)
        ):
            raise ValidationError(
                "This passport received an AI review result and cannot be re-verified automatically.",
                field="post_submission_verification",
            )
        if not self.image_s3_key or self.image_s3_key.startswith("excel-imports/"):
            raise ValidationError(
                "A stored passport front image is required for AI verification.",
                field="image_s3_key",
            )
        if not self.confirmed_fields:
            raise ValidationError(
                "Submitted passport fields are required for AI verification.",
                field="confirmed_fields",
            )

        self.post_submission_verification_revision += 1
        self.status = PassportProcessingStatus.SUBMITTED
        self.post_submission_verification = None
        self.post_submission_verified_at = None
        self.verification_reviewed_by_user_id = None
        self.verification_reviewer_name = None
        self.verification_reviewed_at = None
        self.updated_at = _utcnow()
        return self.post_submission_verification_revision

    def staff_approve_verification(
        self,
        *,
        reviewer_id: uuid.UUID,
        reviewer_name: str,
        expected_extraction_revision: int,
        confirmed_fields: dict[str, str] | None = None,
    ) -> StaffApprovalOutcome:
        """Atomically save optional corrections and transition Needs Review."""

        if self.status == PassportProcessingStatus.STAFF_APPROVED:
            if confirmed_fields is not None and any(
                (self.confirmed_fields or {}).get(key) != value
                for key, value in confirmed_fields.items()
            ):
                raise StaffApprovalUnavailableError(
                    current_status=self.status.value,
                    message=(
                        "This passport was already approved with different field "
                        "values. Refresh the record before taking further action."
                    ),
                )
            return StaffApprovalOutcome.ALREADY_APPROVED
        if self.status != PassportProcessingStatus.NEEDS_REVIEW:
            raise StaffApprovalUnavailableError(
                current_status=self.status.value,
            )
        if expected_extraction_revision != self.extraction_revision:
            raise StaffApprovalStaleError(
                expected_revision=expected_extraction_revision,
                current_revision=self.extraction_revision,
            )

        # Invalidate both extraction and post-submit AI work before publishing
        # the canonical staff decision. Replays return above without incrementing.
        self.extraction_revision += 1
        self.post_submission_verification_revision += 1
        if confirmed_fields is not None:
            self.confirmed_fields = {
                **dict(self.confirmed_fields or {}),
                **dict(confirmed_fields),
            }
            self.extraction_conflicts = []
            if self.post_submission_verification is not None:
                self.post_submission_verification = {
                    **self.post_submission_verification,
                    "stale_after_staff_edit": True,
                }
        now = _utcnow()
        self.status = PassportProcessingStatus.STAFF_APPROVED
        self.verification_reviewed_by_user_id = reviewer_id
        self.verification_reviewer_name = " ".join(reviewer_name.strip().split())[:255]
        self.verification_reviewed_at = now
        self.confirmed_at = now
        self.updated_at = now
        return StaffApprovalOutcome.APPROVED

    def bulk_staff_approve_completed_verification(
        self,
        *,
        reviewer_id: uuid.UUID,
        reviewer_name: str,
    ) -> StaffApprovalOutcome:
        """Approve a completed office record without bypassing in-flight work.

        Bulk review is intentionally narrower than a generic status override:
        completed legacy/imported records, client-submitted records, AI-approved
        records, and rows already awaiting staff review are eligible. Processing
        and failed rows remain untouched until their pipeline finishes.
        """

        if self.status == PassportProcessingStatus.STAFF_APPROVED:
            return StaffApprovalOutcome.ALREADY_APPROVED
        if self.status not in {
            PassportProcessingStatus.CONFIRMED,
            PassportProcessingStatus.CLIENT_SUBMITTED,
            PassportProcessingStatus.SUBMITTED,
            PassportProcessingStatus.AI_APPROVED,
            PassportProcessingStatus.NEEDS_REVIEW,
        }:
            raise StaffApprovalUnavailableError(current_status=self.status.value)

        # Publish a new canonical decision revision while leaving confirmed
        # passport fields unchanged.
        self.extraction_revision += 1
        self.post_submission_verification_revision += 1
        now = _utcnow()
        self.status = PassportProcessingStatus.STAFF_APPROVED
        self.verification_reviewed_by_user_id = reviewer_id
        self.verification_reviewer_name = " ".join(reviewer_name.strip().split())[:255]
        self.verification_reviewed_at = now
        self.confirmed_at = now
        self.updated_at = now
        return StaffApprovalOutcome.APPROVED

    def update_reviewed_fields(self, confirmed_fields: dict[str, str]) -> None:
        """Save staff edits without bypassing the canonical approval transition."""

        self.extraction_revision += 1
        self.confirmed_fields = {
            **dict(self.confirmed_fields or {}),
            **dict(confirmed_fields),
        }
        self.extraction_conflicts = []
        if self.status in {
            PassportProcessingStatus.SUBMITTED,
            PassportProcessingStatus.AI_APPROVED,
            PassportProcessingStatus.NEEDS_REVIEW,
            PassportProcessingStatus.STAFF_APPROVED,
        }:
            self.status = PassportProcessingStatus.NEEDS_REVIEW
            self.verification_reviewed_by_user_id = None
            self.verification_reviewer_name = None
            self.verification_reviewed_at = None
            self.confirmed_at = None
            if self.post_submission_verification is not None:
                self.post_submission_verification = {
                    **self.post_submission_verification,
                    "stale_after_staff_edit": True,
                }
        self.updated_at = _utcnow()
