"""
Passport Application DTOs
=========================
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any


@dataclass(frozen=True)
class PassportSubmissionOutputDTO:
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
    image_s3_key: str
    status: str
    created_at: datetime
    updated_at: datetime
    nearest_domestic_airport: str | None = None
    thumbnail_s3_key: str | None = None
    passport_photo_s3_key: str | None = None
    passport_back_s3_key: str | None = None
    staff_metadata: dict[str, Any] | None = None
    acquisition_mode: str = "file"
    upload_idempotency_key: str | None = None
    extraction_status: str = "not_started"
    extraction_revision: int = 0
    extracted_fields: dict[str, Any] | None = None
    confirmed_fields: dict[str, Any] | None = None
    overall_confidence: float | None = None
    confidence_score: dict[str, Any] | None = None
    mrz_raw: str | None = None
    error_message: str | None = None
    image_url: str | None = None
    client_reviewed_at: datetime | None = None
    confirmed_at: datetime | None = None
    processing_job_id: uuid.UUID | None = None
    processing_job_status: str | None = None
    processing_progress: float | None = None
    processing_stage: str | None = None
    # Internal response-orchestration metadata. Presentation schemas ignore
    # these fields; routes use them only for post-commit storage cleanup.
    storage_cleanup_keys: tuple[str, ...] = ()
    promoted_storage_keys: tuple[str, ...] = ()


def passport_submission_output_from_entity(
    submission: Any,
    *,
    job: Any | None = None,
) -> PassportSubmissionOutputDTO:
    """Map one domain entity consistently across public and dashboard flows."""

    return PassportSubmissionOutputDTO(
        id=submission.id,
        group_id=submission.group_id,
        agency_id=submission.agency_id,
        client_name=submission.client_name,
        client_email=submission.client_email,
        client_phone=submission.client_phone,
        departure_city=submission.departure_city,
        nearest_domestic_airport=submission.nearest_domestic_airport,
        submission_mode=submission.submission_mode,
        family_group_id=submission.family_group_id,
        family_member_index=submission.family_member_index,
        family_relation=submission.family_relation,
        family_gender=submission.family_gender,
        family_head_name=submission.family_head_name,
        family_head_email=submission.family_head_email,
        family_head_phone=submission.family_head_phone,
        family_broadcast_to_member=submission.family_broadcast_to_member,
        image_s3_key=submission.image_s3_key,
        thumbnail_s3_key=submission.thumbnail_s3_key,
        passport_photo_s3_key=submission.passport_photo_s3_key,
        passport_back_s3_key=submission.passport_back_s3_key,
        staff_metadata=submission.staff_metadata,
        acquisition_mode=submission.acquisition_mode,
        upload_idempotency_key=submission.upload_idempotency_key,
        extraction_status=submission.extraction_status.value,
        extraction_revision=submission.extraction_revision,
        status=submission.status.value,
        created_at=submission.created_at,
        updated_at=submission.updated_at,
        extracted_fields=submission.extracted_fields,
        confirmed_fields=submission.confirmed_fields,
        overall_confidence=submission.overall_confidence,
        confidence_score=submission.confidence_score,
        mrz_raw=submission.mrz_raw,
        error_message=submission.error_message,
        client_reviewed_at=submission.client_reviewed_at,
        confirmed_at=submission.confirmed_at,
        processing_job_id=job.id if job else None,
        processing_job_status=job.status.value if job else None,
        processing_progress=job.progress if job else None,
        processing_stage=job.current_stage if job else None,
    )


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
    departure_cities: list[str] | None = None
    base_city_enabled: bool = False
    nearest_international_airport_enabled: bool = False
    staff_code_enabled: bool = False
    meal_preference_enabled: bool = False
    require_selfie: bool = False
    allow_files_from_device: bool = True
    ask_nearest_domestic_airport: bool = False
    notes: str | None = None
