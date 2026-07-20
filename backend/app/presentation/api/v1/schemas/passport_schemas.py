"""
Passport Presentation Schemas
=============================
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class ConfirmPassportSubmissionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirmed_fields: dict[str, str] = Field(..., min_length=1)


class StaffApprovePassportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirmed_fields: dict[str, str] | None = Field(default=None, min_length=1)
    expected_extraction_revision: int = Field(..., ge=0)
    review_reason: str | None = Field(default=None, max_length=240)


class ClientSubmitPassportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirmed_fields: dict[str, str] = Field(..., min_length=1)
    client_email: EmailStr | None = None
    client_phone: str | None = Field(default=None, min_length=7, max_length=32)
    departure_city: str | None = Field(default=None, max_length=120)
    nearest_domestic_airport: str | None = Field(default=None, max_length=120)
    base_city: str | None = Field(default=None, max_length=120)
    staff_code: str | None = Field(default=None, max_length=80)
    meal_preference: str | None = Field(default=None, max_length=20)
    group_token: str = Field(..., min_length=10)
    submission_mode: str = Field(default="single", pattern="^(single|family)$")
    family_group_id: uuid.UUID | None = None
    family_member_index: int | None = Field(default=None, ge=0, le=100)
    family_relation: str | None = Field(default=None, max_length=80)
    family_gender: str | None = Field(default=None, max_length=40)
    family_head_name: str | None = Field(default=None, max_length=255)
    family_head_email: EmailStr | None = None
    family_head_phone: str | None = Field(default=None, min_length=7, max_length=32)


class ReconcilePassportUploadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    upload_idempotency_key: str = Field(
        ...,
        min_length=32,
        max_length=128,
        pattern=r"^[A-Za-z0-9._:-]+$",
    )


class ReconcilePassportUploadResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    submission_id: uuid.UUID | None = None


class ExportSelectedPassportsRequest(BaseModel):
    submission_ids: list[uuid.UUID] = Field(..., min_length=1, max_length=500)


class BulkDeletePassportSubmissionsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    submission_ids: list[uuid.UUID] = Field(..., min_length=1, max_length=100)


class BulkDeletePassportSubmissionsResponse(BaseModel):
    deleted_count: int
    deleted_submission_ids: list[uuid.UUID]
    deleted_storage_objects: int
    deleted_notifications: int
    storage_cleanup_deferred: bool


class ExportSelectedGroupsRequest(BaseModel):
    group_ids: list[uuid.UUID] = Field(..., min_length=1, max_length=100)


class ImportPassportGroupResponse(BaseModel):
    imported_count: int
    updated_count: int = 0
    skipped_count: int


class PassportDocumentImportItem(BaseModel):
    filename: str
    staff_code: str | None = None
    document_type: str | None = None
    passenger_id: uuid.UUID | None = None
    passenger_name: str | None = None
    accepted: bool
    reason: str | None = None


class PassportDocumentImportPreviewResponse(BaseModel):
    group_id: uuid.UUID
    total_count: int
    accepted_count: int
    rejected_count: int
    accepted_documents: list[PassportDocumentImportItem] = Field(default_factory=list)
    rejected_documents: list[PassportDocumentImportItem] = Field(default_factory=list)


class PassportDocumentImportSaveResponse(PassportDocumentImportPreviewResponse):
    saved_count: int


class PassengerQrStatusResponse(BaseModel):
    status: str
    token_version: int | None = None
    created_at: datetime | None = None
    expires_at: datetime | None = None
    revoked_at: datetime | None = None


class PassportExtractionConflictResponse(BaseModel):
    field: str
    manual_value: str
    extracted_value: str | None = None
    status: Literal["mismatch", "not_extracted"]


PassportVerificationFieldName = Literal[
    "surname",
    "given_names",
    "passport_number",
    "nationality",
    "issuing_country",
    "date_of_birth",
    "date_of_issue",
    "date_of_expiry",
    "sex",
]


class PostSubmissionFieldOutcomeResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field: PassportVerificationFieldName
    verdict: Literal["correct", "suspicious", "incorrect"]
    observed_value: str | None = Field(default=None, max_length=100)
    confidence: float = Field(..., ge=0.0, le=1.0)
    reason_code: str = Field(..., min_length=1, max_length=64)


class PostSubmissionVerificationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verification_status: Literal["ai_approved", "needs_review"]
    confidence: float = Field(..., ge=0.0, le=1.0)
    incorrect_fields: list[PassportVerificationFieldName] = Field(default_factory=list)
    suspicious_fields: list[PassportVerificationFieldName] = Field(default_factory=list)
    explanation: str = Field(..., min_length=1, max_length=240)
    provider_status: str = Field(..., min_length=1, max_length=64)
    reason_code: str | None = Field(default=None, max_length=64)
    model: str | None = Field(default=None, max_length=120)
    fields: list[PostSubmissionFieldOutcomeResponse] = Field(default_factory=list)
    stale_after_staff_edit: bool = False


class PassportSubmissionResponse(BaseModel):
    id: uuid.UUID
    group_id: uuid.UUID
    agency_id: uuid.UUID
    client_name: str
    client_email: str | None = None
    client_phone: str | None = None
    departure_city: str | None = None
    nearest_domestic_airport: str | None = None
    submission_mode: str = "single"
    family_group_id: uuid.UUID | None = None
    family_member_index: int | None = None
    family_relation: str | None = None
    family_gender: str | None = None
    family_head_name: str | None = None
    family_head_email: str | None = None
    family_head_phone: str | None = None
    family_broadcast_to_member: bool = False
    image_s3_key: str
    thumbnail_s3_key: str | None = None
    passport_photo_s3_key: str | None = None
    passport_back_s3_key: str | None = None
    staff_metadata: dict[str, str] | None = None
    acquisition_mode: Literal["camera", "file"] = "file"
    qualifier_enabled_snapshot: bool = False
    qualifier_is_self: bool | None = None
    qualifier_relation_code: str | None = Field(default=None, max_length=40)
    qualifier_relation_label: str | None = Field(default=None, max_length=80)
    qualifier_selected_at: datetime | None = None
    extraction_status: Literal[
        "not_started",
        "processing",
        "extraction_complete",
        "extraction_partial",
        "extraction_failed",
        "ready_for_review",
    ] = "not_started"
    extraction_revision: int = Field(default=0, ge=0)
    status: str
    created_at: datetime
    updated_at: datetime
    extracted_fields: dict | None = None
    confirmed_fields: dict | None = None
    extraction_conflicts: list[PassportExtractionConflictResponse] = Field(
        default_factory=list
    )
    overall_confidence: float | None = None
    confidence_score: dict | None = None
    mrz_raw: str | None = None
    error_message: str | None = None
    image_url: str | None = None
    passport_photo_url: str | None = None
    passport_back_url: str | None = None
    client_reviewed_at: datetime | None = None
    confirmed_at: datetime | None = None
    post_submission_verification: PostSubmissionVerificationResponse | None = None
    post_submission_verification_revision: int = Field(default=0, ge=0)
    post_submission_verified_at: datetime | None = None
    verification_reviewed_by_user_id: uuid.UUID | None = None
    verification_reviewer_name: str | None = None
    verification_reviewed_at: datetime | None = None
    processing_job_id: uuid.UUID | None = None
    processing_job_status: str | None = None
    processing_progress: float | None = None
    processing_stage: str | None = None
    qr_status: PassengerQrStatusResponse | None = None

    model_config = {"from_attributes": True}


class PassportSubmissionViewItemResponse(PassportSubmissionResponse):
    duplicate_cluster_id: str | None = None
    duplicate_cluster_size: int = Field(default=1, ge=1)
    duplicate_cluster_member_ids: list[uuid.UUID] = Field(
        default_factory=list
    )
    verification_confidence: float | None = Field(
        default=None, ge=0.0, le=1.0
    )


class PassportExpiryAlertResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    submission_id: uuid.UUID
    client_name: str
    client_email: str | None = None
    passport_number: str | None = None
    date_of_expiry: date
    status: Literal["expired", "near_expiry"]


class PassportSubmissionsViewResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[PassportSubmissionViewItemResponse] = Field(
        default_factory=list
    )
    group_total: int = Field(ge=0)
    total: int = Field(ge=0)
    page: int = Field(ge=1)
    page_size: int = Field(ge=1)
    total_pages: int = Field(ge=0)
    returned_count: int = Field(ge=0)
    cluster_boundaries_preserved: bool = True
    expiry_alerts: list[PassportExpiryAlertResponse] = Field(
        default_factory=list
    )


class PassportGroupSummaryResponse(BaseModel):
    group_id: uuid.UUID
    group_name: str
    group_status: str
    total_passports: int
    pending_review_count: int
    confirmed_count: int
    failed_count: int
    latest_submission_at: datetime
    destination: str | None = None
    travel_date: date | None = None
    return_date: date | None = None
    package_name: str | None = None
    departure_cities: list[str] = Field(default_factory=list)
    base_city_enabled: bool = False
    nearest_international_airport_enabled: bool = False
    staff_code_enabled: bool = False
    meal_preference_enabled: bool = False
    require_selfie: bool = False
    allow_files_from_device: bool = True
    ask_nearest_domestic_airport: bool = False
    relation_with_qualifier_enabled: bool = False
    notes: str | None = None

    model_config = {"from_attributes": True}
