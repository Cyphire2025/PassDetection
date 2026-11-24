"""Focused passport view API contracts."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .passport_document_schemas import PassengerQrStatusResponse, PassportExtractionConflictResponse
from .passport_verification_schemas import PostSubmissionVerificationResponse


class PassportSubmissionResponse(BaseModel):
    id: uuid.UUID
    group_id: uuid.UUID
    agency_id: uuid.UUID
    client_name: str
    display_name: str | None = None
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
    passport_cover_s3_key: str | None = None
    passport_back_cover_s3_key: str | None = None
    passport_back_s3_key: str | None = None
    staff_metadata: dict[str, str] | None = None
    document_follow_up: bool = False
    custom_answers: list[dict[str, str]] = Field(default_factory=list)
    custom_detail_answers: list[dict[str, str]] = Field(default_factory=list)
    acquisition_mode: Literal["camera", "file"] = "file"
    qualifier_enabled_snapshot: bool = False
    qualifier_is_self: bool | None = None
    qualifier_relation_code: str | None = Field(default=None, max_length=40)
    qualifier_relation_label: str | None = Field(default=None, max_length=100)
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
    manual_review_submission_allowed: bool = False
    manual_review_reason_code: Literal["AI_EXTRACTION_UNAVAILABLE"] | None = None
    status: str
    created_at: datetime
    updated_at: datetime
    extracted_fields: dict[str, object] | None = None
    confirmed_fields: dict[str, str] | None = None
    extraction_conflicts: list[PassportExtractionConflictResponse] = Field(default_factory=list)
    overall_confidence: float | None = None
    confidence_score: dict[str, object] | None = None
    mrz_raw: str | None = None
    error_message: str | None = None
    image_url: str | None = None
    passport_photo_url: str | None = None
    passport_back_url: str | None = None
    passport_cover_url: str | None = None
    passport_back_cover_url: str | None = None
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
        default_factory=list,
        description="Legacy complete membership for small sets; otherwise empty. See duplicate_clusters.",
    )
    duplicate_cluster_member_ids_complete: bool = Field(
        default=True,
        description="False means membership is omitted, not that the set has no members.",
    )
    verification_confidence: float | None = Field(default=None, ge=0.0, le=1.0)


class PassportSubmissionSelectionSnapshotResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    submission_id: uuid.UUID
    extraction_revision: int = Field(ge=0)


class PassportExpiryAlertResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    submission_id: uuid.UUID
    client_name: str
    client_email: str | None = None
    passport_number: str | None = None
    date_of_expiry: date
    status: Literal["expired", "near_expiry"]


class PassportDuplicateClusterPageResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    cluster_id: str
    total_members: int = Field(ge=2)
    matching_members: int = Field(ge=1)
    visible_member_ids: list[uuid.UUID] = Field(
        description="Set members hydrated on this page only."
    )
    first_page: int = Field(
        ge=1, description="First matching page under the current filters and sort."
    )
    last_page: int = Field(
        ge=1, description="Last matching page; navigate through this page to see all matches."
    )


class PassportSubmissionsViewResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[PassportSubmissionViewItemResponse] = Field(default_factory=list)
    ordered_submission_ids: list[uuid.UUID] = Field(default_factory=list)
    ordered_selection_snapshot: list[PassportSubmissionSelectionSnapshotResponse] = Field(
        default_factory=list
    )
    group_total: int = Field(ge=0)
    document_follow_up_count: int = Field(default=0, ge=0)
    total: int = Field(ge=0)
    page: int = Field(ge=1)
    page_size: int = Field(ge=1)
    total_pages: int = Field(ge=0)
    returned_count: int = Field(ge=0)
    cluster_boundaries_preserved: bool = True
    duplicate_metadata_version: Literal[2] = Field(
        default=2,
        description="Bounded rows with normalized duplicate membership and page continuations.",
    )
    duplicate_clusters: list[PassportDuplicateClusterPageResponse] = Field(default_factory=list)
    expiry_alerts: list[PassportExpiryAlertResponse] = Field(default_factory=list)
