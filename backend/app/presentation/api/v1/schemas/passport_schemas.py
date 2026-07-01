"""
Passport Presentation Schemas
=============================
"""

from __future__ import annotations

import uuid
from datetime import datetime
from pydantic import BaseModel, EmailStr, Field


class ConfirmPassportSubmissionRequest(BaseModel):
    confirmed_fields: dict[str, str] = Field(..., min_length=1)


class ClientSubmitPassportRequest(BaseModel):
    confirmed_fields: dict[str, str] = Field(..., min_length=1)
    client_email: EmailStr
    client_phone: str = Field(..., min_length=7, max_length=32)
    group_token: str = Field(..., min_length=10)


class PassportSubmissionResponse(BaseModel):
    id: uuid.UUID
    group_id: uuid.UUID
    agency_id: uuid.UUID
    client_name: str
    client_email: str | None = None
    client_phone: str | None = None
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

    model_config = {"from_attributes": True}
