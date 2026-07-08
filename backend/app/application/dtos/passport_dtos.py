"""
Passport Application DTOs
=========================
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime


@dataclass(frozen=True)
class PassportSubmissionOutputDTO:
    id: uuid.UUID
    group_id: uuid.UUID
    agency_id: uuid.UUID
    client_name: str
    client_email: str | None
    client_phone: str | None
    image_s3_key: str
    status: str
    created_at: datetime
    updated_at: datetime
    thumbnail_s3_key: str | None = None
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


@dataclass(frozen=True)
class PassportGroupSummaryDTO:
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
    notes: str | None = None
