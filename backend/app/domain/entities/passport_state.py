"""Stored submission fields and derived manual-review eligibility."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime

from app.domain.entities.enums import PassportExtractionStatus, PassportProcessingStatus
from app.domain.entities.factories import _utcnow
from app.domain.value_objects.custom_questions import (
    CustomAnswerSnapshot,
    CustomDetailAnswerSnapshot,
)
from app.domain.value_objects.passport_document_classification import (
    manual_review_submission_allowed,
)


@dataclass
class PassportSubmissionState:
    """Fields shared by extraction, collection and verification transitions."""

    id: uuid.UUID
    group_id: uuid.UUID
    agency_id: uuid.UUID

    client_name: str
    client_email: str | None
    client_phone: str | None
    departure_city: str | None

    submission_mode: str
    family_group_id: uuid.UUID | None
    family_member_index: int | None
    family_relation: str | None
    family_gender: str | None
    family_head_name: str | None
    family_head_email: str | None
    family_head_phone: str | None
    family_broadcast_to_member: bool

    image_s3_key: str  # Key in S3 bucket
    thumbnail_s3_key: str | None
    passport_photo_s3_key: str | None
    passport_back_s3_key: str | None

    staff_metadata: dict[str, str] | None

    status: PassportProcessingStatus
    extracted_fields: dict[str, object] | None  # Raw extraction result
    confirmed_fields: dict[str, str] | None  # Client-reviewed final data
    overall_confidence: float | None
    confidence_score: dict[str, object] | None  # Layered confidence breakdown
    mrz_raw: str | None  # Raw MRZ string
    error_message: str | None

    passport_cover_s3_key: str | None = None
    passport_back_cover_s3_key: str | None = None
    document_follow_up: bool = False
    display_name: str | None = None

    custom_answers: list[CustomAnswerSnapshot] = field(default_factory=list)
    custom_detail_answers: list[CustomDetailAnswerSnapshot] = field(default_factory=list)

    qualifier_enabled_snapshot: bool = False
    qualifier_selection_id: uuid.UUID | None = None
    qualifier_is_self: bool | None = None
    qualifier_relation_code: str | None = None
    qualifier_relation_label: str | None = None
    qualifier_selected_at: datetime | None = None

    nearest_domestic_airport: str | None = None

    acquisition_mode: str = "file"
    upload_idempotency_key: str | None = None

    extraction_status: PassportExtractionStatus = PassportExtractionStatus.NOT_STARTED
    extraction_revision: int = 0
    extraction_conflicts: list[dict[str, str | None]] = field(default_factory=list)

    post_submission_verification: dict[str, object] | None = None
    post_submission_verification_revision: int = 0
    post_submission_verified_at: datetime | None = None
    verification_reviewed_by_user_id: uuid.UUID | None = None
    verification_reviewer_name: str | None = None
    verification_reviewed_at: datetime | None = None

    created_at: datetime = field(default_factory=_utcnow)
    updated_at: datetime = field(default_factory=_utcnow)
    client_reviewed_at: datetime | None = None
    confirmed_at: datetime | None = None

    @property
    def manual_review_submission_allowed(self) -> bool:
        return manual_review_submission_allowed(
            extracted_fields=self.extracted_fields,
            extraction_revision=self.extraction_revision,
            extraction_status=self.extraction_status.value,
            status=self.status.value,
            image_s3_key=self.image_s3_key,
        )
