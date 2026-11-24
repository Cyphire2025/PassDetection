"""Public passport submission construction and stored image keys."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from app.domain.entities.enums import PassportExtractionStatus, PassportProcessingStatus
from app.domain.entities.factories import _new_uuid, _utcnow
from app.domain.entities.passport_client_review import PassportClientReview
from app.domain.entities.passport_extraction import PassportExtraction
from app.domain.entities.passport_staff_review import PassportStaffReview
from app.domain.entities.qualifier_selection import QualifierSelection
from app.domain.exceptions.exceptions import ValidationError


@dataclass
class PassportSubmission(PassportExtraction, PassportClientReview, PassportStaffReview):
    """
    Represents a passport image submitted by a client.

    This is the central entity of the platform.
    It tracks the image, extracted fields, processing status,
    and confidence scores.
    """

    @classmethod
    def create(
        cls,
        group_id: uuid.UUID,
        agency_id: uuid.UUID,
        client_name: str,
        client_email: str | None,
        image_s3_key: str,
        acquisition_mode: str = "file",
        upload_idempotency_key: str | None = None,
    ) -> PassportSubmission:
        normalized_acquisition_mode = acquisition_mode.strip().lower()
        if normalized_acquisition_mode not in {"camera", "file"}:
            raise ValidationError(
                "Choose a supported passport capture method.",
                field="acquisition_mode",
            )
        normalized_idempotency_key = (
            upload_idempotency_key.strip() if upload_idempotency_key else None
        )
        if normalized_idempotency_key and len(normalized_idempotency_key) > 128:
            raise ValidationError(
                "Upload idempotency key is too long.",
                field="upload_idempotency_key",
            )
        return cls(
            id=_new_uuid(),
            group_id=group_id,
            agency_id=agency_id,
            client_name=client_name.strip(),
            client_email=client_email.lower().strip() if client_email else None,
            client_phone=None,
            departure_city=None,
            nearest_domestic_airport=None,
            submission_mode="single",
            family_group_id=None,
            family_member_index=None,
            family_relation=None,
            family_gender=None,
            family_head_name=None,
            family_head_email=None,
            family_head_phone=None,
            family_broadcast_to_member=False,
            image_s3_key=image_s3_key,
            thumbnail_s3_key=None,
            passport_photo_s3_key=None,
            passport_back_s3_key=None,
            acquisition_mode=normalized_acquisition_mode,
            upload_idempotency_key=normalized_idempotency_key,
            extraction_status=PassportExtractionStatus.NOT_STARTED,
            extraction_revision=0,
            extraction_conflicts=[],
            post_submission_verification=None,
            post_submission_verification_revision=0,
            post_submission_verified_at=None,
            verification_reviewed_by_user_id=None,
            verification_reviewer_name=None,
            verification_reviewed_at=None,
            staff_metadata=None,
            status=PassportProcessingStatus.PENDING_EXTRACTION,
            extracted_fields=None,
            confirmed_fields=None,
            overall_confidence=None,
            confidence_score=None,
            mrz_raw=None,
            error_message=None,
        )

    def attach_qualifier_selection(self, selection: QualifierSelection) -> None:
        """Snapshot one validated selection onto this single passenger."""

        if selection.group_id != self.group_id:
            raise ValidationError(
                "The qualifier selection does not belong to this upload link.",
                field="qualifier_selection_token",
            )
        self.qualifier_enabled_snapshot = True
        self.qualifier_selection_id = selection.id
        self.qualifier_is_self = selection.is_self
        self.qualifier_relation_code = selection.relation_code
        self.qualifier_relation_label = selection.relation_label
        self.qualifier_selected_at = selection.selected_at
        self.updated_at = _utcnow()

    def promote_passport_cover(self, key: str) -> None:
        self.passport_cover_s3_key = key
        self.updated_at = _utcnow()

    def promote_passport_back_cover(self, key: str) -> None:
        self.passport_back_cover_s3_key = key
        self.updated_at = _utcnow()

    def snapshot_collection_labels(
        self,
        *,
        agent_employee_code_label: str | None,
        agency_dealership_name_label: str | None,
    ) -> None:
        metadata = dict(self.staff_metadata or {})
        for name, label in (
            ("agent_employee_code_label", agent_employee_code_label),
            ("agency_dealership_name_label", agency_dealership_name_label),
        ):
            if label:
                metadata[name] = label
        self.staff_metadata = metadata or None

    def promote_image(self, permanent_key: str) -> None:
        self.image_s3_key = permanent_key
        self.updated_at = _utcnow()

    def promote_passport_photo(self, permanent_key: str) -> None:
        self.passport_photo_s3_key = permanent_key
        self.updated_at = _utcnow()

    def promote_passport_back(self, permanent_key: str) -> None:
        self.passport_back_s3_key = permanent_key
        self.updated_at = _utcnow()
