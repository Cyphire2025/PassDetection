"""Client corrections and submission with family and contact snapshots."""

from __future__ import annotations

import uuid

from app.domain.entities.enums import (
    OFFICE_VISIBLE_PASSPORT_STATUS_VALUES,
    PassportExtractionStatus,
    PassportProcessingStatus,
)
from app.domain.entities.factories import _utcnow
from app.domain.entities.passport_state import PassportSubmissionState
from app.domain.exceptions.exceptions import ValidationError
from app.domain.value_objects.custom_questions import (
    CustomAnswerSnapshot,
    CustomDetailAnswerSnapshot,
)


class PassportClientReview(PassportSubmissionState):
    """Retain client corrections and publish one submitted snapshot."""

    def confirm(self, confirmed_fields: dict[str, str]) -> None:
        # Invalidate any extraction job that started before this correction.
        self.extraction_revision += 1
        if self.extraction_status == PassportExtractionStatus.PROCESSING:
            self.extraction_status = PassportExtractionStatus.READY_FOR_REVIEW
        self.status = PassportProcessingStatus.CONFIRMED
        self.confirmed_fields = confirmed_fields
        self.extraction_conflicts = []
        self.confirmed_at = _utcnow()
        self.updated_at = _utcnow()

    def submit_client_review(
        self,
        confirmed_fields: dict[str, str],
        *,
        client_email: str | None,
        client_phone: str | None,
        departure_city: str | None = None,
        submission_mode: str = "single",
        family_group_id: uuid.UUID | None = None,
        family_member_index: int | None = None,
        family_relation: str | None = None,
        family_gender: str | None = None,
        family_head_name: str | None = None,
        family_head_email: str | None = None,
        family_head_phone: str | None = None,
        family_broadcast_to_member: bool = False,
        nearest_domestic_airport: str | None = None,
        custom_answers: list[CustomAnswerSnapshot] | None = None,
        custom_detail_answers: list[CustomDetailAnswerSnapshot] | None = None,
        allow_manual_submission: bool = False,
        allow_returning_snapshot_review: bool = False,
    ) -> None:
        returning_snapshot = (
            allow_returning_snapshot_review
            and self.status == PassportProcessingStatus.CONFIRMED
            and (self.staff_metadata or {}).get("reuse_assignment") == "automatic"
            and self.client_reviewed_at is None
            and self.confirmed_at is None
            and self.verification_reviewed_at is None
            and self.verification_reviewed_by_user_id is None
            and self.post_submission_verified_at is None
            and self.post_submission_verification is None
        )
        if self.status.value in OFFICE_VISIBLE_PASSPORT_STATUS_VALUES and not returning_snapshot:
            raise ValidationError(
                "Passport details were already submitted.",
                field="status",
            )
        if allow_manual_submission and not self.manual_review_submission_allowed:
            raise ValidationError(
                "This passport is not eligible for manual submission for AI verification.",
                field="file",
            )
        # Invalidate any extraction job that started before this correction.
        self.extraction_revision += 1
        if self.extraction_status == PassportExtractionStatus.PROCESSING:
            self.extraction_status = PassportExtractionStatus.READY_FOR_REVIEW
        self.status = PassportProcessingStatus.SUBMITTED
        self.client_email = client_email.lower().strip() if client_email else None
        self.client_phone = client_phone.strip() if client_phone else None
        self.departure_city = departure_city.strip() if departure_city else None
        normalized_domestic_airport = (
            " ".join(nearest_domestic_airport.strip().split()) if nearest_domestic_airport else None
        )
        if normalized_domestic_airport and len(normalized_domestic_airport) > 120:
            raise ValidationError(
                "Nearest domestic airport must be 120 characters or fewer.",
                field="nearest_domestic_airport",
            )
        self.nearest_domestic_airport = normalized_domestic_airport
        self.custom_answers = list(custom_answers or [])
        self.custom_detail_answers = list(custom_detail_answers or [])
        self.submission_mode = submission_mode
        self.family_group_id = family_group_id
        self.family_member_index = family_member_index
        self.family_relation = family_relation.strip() if family_relation else None
        self.family_gender = family_gender.strip() if family_gender else None
        self.family_head_name = family_head_name.strip() if family_head_name else None
        self.family_head_email = family_head_email.lower().strip() if family_head_email else None
        self.family_head_phone = family_head_phone.strip() if family_head_phone else None
        self.family_broadcast_to_member = family_broadcast_to_member
        self.confirmed_fields = confirmed_fields
        passport_name = " ".join(
            str(confirmed_fields.get(field_name) or "").strip()
            for field_name in ("given_names", "surname")
        ).strip()
        if passport_name:
            self.client_name = " ".join(passport_name.split())[:255]
        self.extraction_conflicts = []
        self.post_submission_verification_revision += 1
        self.post_submission_verification = None
        self.post_submission_verified_at = None
        self.verification_reviewed_by_user_id = None
        self.verification_reviewer_name = None
        self.verification_reviewed_at = None
        self.client_reviewed_at = _utcnow()
        self.updated_at = _utcnow()
        # A trusted first-pass provider failure allows manual entry; it must not
        # skip the independent image-based verification of the submitted values.
        # Keep the original failure diagnostics in extracted_fields for audit.
        self.error_message = None
