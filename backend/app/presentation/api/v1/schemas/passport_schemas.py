"""
Passport Presentation Schemas
=============================
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from pydantic import BaseModel, EmailStr, Field


class ConfirmPassportSubmissionRequest(BaseModel):
    confirmed_fields: dict[str, str] = Field(..., min_length=1)


class ClientSubmitPassportRequest(BaseModel):
    confirmed_fields: dict[str, str] = Field(..., min_length=1)
    client_email: EmailStr | None = None
    client_phone: str | None = Field(default=None, min_length=7, max_length=32)
    departure_city: str | None = Field(default=None, max_length=120)
    group_token: str = Field(..., min_length=10)
    submission_mode: str = Field(default="single", pattern="^(single|family)$")
    family_group_id: uuid.UUID | None = None
    family_member_index: int | None = Field(default=None, ge=0, le=100)
    family_relation: str | None = Field(default=None, max_length=80)
    family_gender: str | None = Field(default=None, max_length=40)
    family_head_name: str | None = Field(default=None, max_length=255)
    family_head_email: EmailStr | None = None
    family_head_phone: str | None = Field(default=None, min_length=7, max_length=32)


class ExportSelectedPassportsRequest(BaseModel):
    submission_ids: list[uuid.UUID] = Field(..., min_length=1, max_length=500)


class ExportSelectedGroupsRequest(BaseModel):
    group_ids: list[uuid.UUID] = Field(..., min_length=1, max_length=100)


class ImportPassportGroupResponse(BaseModel):
    imported_count: int
    skipped_count: int


class PassengerQrStatusResponse(BaseModel):
    status: str
    token_version: int | None = None
    created_at: datetime | None = None
    expires_at: datetime | None = None
    revoked_at: datetime | None = None


class PassportSubmissionResponse(BaseModel):
    id: uuid.UUID
    group_id: uuid.UUID
    agency_id: uuid.UUID
    client_name: str
    client_email: str | None = None
    client_phone: str | None = None
    departure_city: str | None = None
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
    status: str
    created_at: datetime
    updated_at: datetime
    extracted_fields: dict | None = None
    confirmed_fields: dict | None = None
    overall_confidence: float | None = None
    confidence_score: dict | None = None
    mrz_raw: str | None = None
    error_message: str | None = None
    image_url: str | None = None
    client_reviewed_at: datetime | None = None
    confirmed_at: datetime | None = None
    processing_job_id: uuid.UUID | None = None
    processing_job_status: str | None = None
    processing_progress: float | None = None
    processing_stage: str | None = None
    qr_status: PassengerQrStatusResponse | None = None

    model_config = {"from_attributes": True}


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
    notes: str | None = None

    model_config = {"from_attributes": True}
