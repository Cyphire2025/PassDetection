"""
Tour Operations API Schemas
===========================
Phase 1 exposes module architecture and implementation status only.
Workflow endpoints are added in later phases.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator

from app.presentation.api.v1.schemas.attendance_closeout_schemas import (
    AttendanceCloseoutStatusResponse,
)


class TourOperationsPhaseResponse(BaseModel):
    phase: int
    name: str
    status: str = Field(..., pattern="^(planned|in_progress|completed)$")
    scope: list[str]


class TourOperationsArchitectureResponse(BaseModel):
    module: str
    current_phase: int
    principles: list[str]
    permissions: dict[str, list[str]]
    data_entities: list[str]
    offline_strategy: list[str]
    navigation: list[str]
    phases: list[TourOperationsPhaseResponse]


class CreateCoordinatorRequest(BaseModel):
    full_name: str = Field(..., min_length=2, max_length=255)
    email: EmailStr
    password: str = Field(..., min_length=10, max_length=128)

    @field_validator("password")
    @classmethod
    def validate_password(cls, value: str) -> str:
        from app.core.security.password import validate_password_strength

        validate_password_strength(value)
        return value


class CoordinatorResponse(BaseModel):
    id: uuid.UUID
    full_name: str
    email: EmailStr
    agency_id: uuid.UUID
    is_active: bool
    created_at: datetime
    last_login_at: datetime | None = None
    assigned_groups_count: int = 0
    assigned_passengers_count: int = 0


class GroupCoordinatorAssignmentResponse(BaseModel):
    coordinator_id: uuid.UUID
    full_name: str
    email: EmailStr
    assigned_passengers_count: int


class TourOperationsGroupResponse(BaseModel):
    id: uuid.UUID
    name: str
    status: str
    destination: str | None = None
    travel_date: str | None = None
    return_date: str | None = None
    timezone: str = "Asia/Kolkata"
    departure_cities: list[str] = Field(default_factory=list)
    base_city_enabled: bool = False
    nearest_international_airport_enabled: bool = False
    staff_code_enabled: bool = False
    agent_employee_code_enabled: bool = False
    meal_preference_enabled: bool = False
    require_selfie: bool = False
    passenger_count: int
    assigned_passengers_count: int
    unassigned_passengers_count: int
    coordinators: list[GroupCoordinatorAssignmentResponse] = Field(default_factory=list)


class AssignGroupCoordinatorsRequest(BaseModel):
    coordinator_ids: list[uuid.UUID] = Field(default_factory=list)


class AssignGroupPassengersRequest(BaseModel):
    passenger_ids: list[uuid.UUID] = Field(..., min_length=1)
    coordinator_id: uuid.UUID | None = None


class AssignedPassengerResponse(BaseModel):
    id: uuid.UUID
    client_name: str
    client_email: str | None = None
    client_phone: str | None = None
    departure_city: str | None = None
    submission_mode: str = "single"
    family_group_id: uuid.UUID | None = None
    family_group_label: str | None = None
    family_member_index: int | None = None
    family_relation: str | None = None
    family_gender: str | None = None
    family_size: int = 1
    family_head_name: str | None = None
    status: str
    coordinator_id: uuid.UUID | None = None
    coordinator_name: str | None = None
    qr_payload: str | None = None


class AssignedPassengerDetailResponse(AssignedPassengerResponse):
    created_at: datetime
    updated_at: datetime
    client_reviewed_at: datetime | None = None
    confirmed_at: datetime | None = None
    passport_fields: dict[str, Any] = Field(default_factory=dict)
    overall_confidence: float | None = None


class GroupPassengerQrCodeResponse(BaseModel):
    passenger_id: uuid.UUID
    client_name: str
    client_email: str | None = None
    client_phone: str | None = None
    departure_city: str | None = None
    coordinator_id: uuid.UUID | None = None
    coordinator_name: str | None = None
    qr_status: str
    qr_token_version: int | None = None
    qr_created_at: datetime | None = None
    qr_expires_at: datetime | None = None
    qr_revoked_at: datetime | None = None
    qr_payload: str | None = None


class GroupPassengerQrCodesResponse(BaseModel):
    group_id: uuid.UUID
    group_name: str
    generated_at: datetime
    passengers: list[GroupPassengerQrCodeResponse] = Field(default_factory=list)


class QrDeliveryPreviewRecipient(BaseModel):
    passenger_id: uuid.UUID
    passenger_name: str
    passport_number: str | None = None
    qr_token_id: uuid.UUID | None = None
    qr_token_version: int | None = None
    qr_status: str
    recipient_id: uuid.UUID | None = None
    broadcast_group_id: uuid.UUID | None = None
    broadcast_name: str | None = None
    phone_number: str | None = None
    delivery_id: uuid.UUID | None = None
    delivery_status: str
    eligible: bool = False
    reason: str
    error_message: str | None = None
    message_preview: str | None = None


class QrDeliveryPreviewSummary(BaseModel):
    total_passengers: int = 0
    ready: int = 0
    retryable: int = 0
    already_sent: int = 0
    in_progress: int = 0
    blocked: int = 0
    ambiguous_recipients: int = 0


class QrDeliveryPreviewResponse(BaseModel):
    group_id: uuid.UUID
    template_name: str | None = None
    template_configured: bool = False
    linked_broadcast_count: int = 0
    can_send: bool = False
    configuration_error: str | None = None
    message_content: str
    summary: QrDeliveryPreviewSummary
    recipients: list[QrDeliveryPreviewRecipient] = Field(default_factory=list)


class SendQrBroadcastRequest(BaseModel):
    qr_token_ids: list[uuid.UUID] | None = Field(default=None, max_length=500)
    message_content: str = Field(min_length=1, max_length=600)


class SendQrBroadcastResponse(BaseModel):
    send_batch_id: uuid.UUID | None = None
    queued_count: int = 0
    skipped_count: int = 0
    message: str


class PassengerQrTokenResponse(BaseModel):
    passenger_id: uuid.UUID
    status: str
    token_version: int
    created_at: datetime
    expires_at: datetime
    revoked_at: datetime | None = None
    qr_payload: str | None = None


class SetPassengerQrActiveRequest(BaseModel):
    is_active: bool


class SetPassengerQrExpirationRequest(BaseModel):
    expires_at: datetime


class CreateAttendanceSessionRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=160)
    scheduled_starts_at: datetime | None = None
    scheduled_ends_at: datetime | None = None
    schedule_timezone: str | None = Field(default=None, min_length=1, max_length=64)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if len(normalized) < 2:
            raise ValueError("Activity name must contain at least 2 characters.")
        return normalized

    @model_validator(mode="after")
    def validate_schedule(self) -> CreateAttendanceSessionRequest:
        _validate_attendance_schedule(
            starts_at=self.scheduled_starts_at,
            ends_at=self.scheduled_ends_at,
            timezone_name=self.schedule_timezone,
            allow_omitted=True,
        )
        return self


class UpdateAttendanceScheduleRequest(BaseModel):
    scheduled_starts_at: datetime
    scheduled_ends_at: datetime
    schedule_timezone: str = Field(min_length=1, max_length=64)

    @model_validator(mode="after")
    def validate_schedule(self) -> UpdateAttendanceScheduleRequest:
        _validate_attendance_schedule(
            starts_at=self.scheduled_starts_at,
            ends_at=self.scheduled_ends_at,
            timezone_name=self.schedule_timezone,
            allow_omitted=False,
        )
        return self


class AttendanceSessionResponse(BaseModel):
    id: uuid.UUID
    group_id: uuid.UUID
    name: str
    status: str
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    scheduled_starts_at: datetime | None = None
    scheduled_ends_at: datetime | None = None
    schedule_timezone: str | None = None
    schedule_version: int = Field(default=1, ge=1)
    scanned_count: int = 0
    assigned_count: int = 0


def _validate_attendance_schedule(
    *,
    starts_at: datetime | None,
    ends_at: datetime | None,
    timezone_name: str | None,
    allow_omitted: bool,
) -> None:
    values = (starts_at, ends_at, timezone_name)
    if all(value is None for value in values):
        if allow_omitted:
            return
        raise ValueError("Attendance schedule is required")
    if any(value is None for value in values):
        raise ValueError("Attendance start, end, and time zone must be provided together")
    if starts_at is None or ends_at is None or timezone_name is None:
        raise ValueError("Attendance schedule is incomplete")
    if starts_at.tzinfo is None or starts_at.utcoffset() is None:
        raise ValueError("Attendance start must include a timezone offset")
    if ends_at.tzinfo is None or ends_at.utcoffset() is None:
        raise ValueError("Attendance end must include a timezone offset")
    if ends_at <= starts_at:
        raise ValueError("Attendance end must be after the start")
    normalized_timezone = timezone_name.strip()
    if normalized_timezone != timezone_name:
        raise ValueError("Attendance time zone must not contain surrounding whitespace")
    try:
        ZoneInfo(normalized_timezone)
    except (ValueError, ZoneInfoNotFoundError) as exc:
        raise ValueError("Attendance time zone must be a valid IANA time zone") from exc


class AttendanceScanRequest(BaseModel):
    qr_payload: str = Field(..., min_length=49, max_length=49, pattern=r"^pdatt:[A-Za-z0-9_-]{43}$")
    client_event_id: str = Field(..., min_length=8, max_length=128, pattern=r"^[A-Za-z0-9:_-]+$")
    scanned_at: datetime | None = None
    device_id: str | None = Field(default=None, max_length=128, pattern=r"^[A-Za-z0-9:_-]+$")
    runtime_id: uuid.UUID | None = None
    sync_source: str = Field(default="online", pattern="^(online|offline)$")

    @field_validator("scanned_at")
    @classmethod
    def require_scan_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("scanned_at must include a timezone offset")
        return value


class AttendanceScanResponse(BaseModel):
    session_id: uuid.UUID
    passenger_id: uuid.UUID | None = None
    passenger_name: str | None = None
    status: str
    message: str
    scanned_count: int
    assigned_count: int


ATTENDANCE_SCAN_BATCH_MAX_ITEMS = 50
ATTENDANCE_SCAN_BATCH_MAX_AGGREGATE_BYTES = 16 * 1024


class AttendanceScanBatchItemRequest(BaseModel):
    client_event_id: str = Field(
        ...,
        min_length=8,
        max_length=128,
        pattern=r"^[A-Za-z0-9:_-]+$",
    )
    qr_payload: str = Field(
        ...,
        min_length=49,
        max_length=49,
        pattern=r"^pdatt:[A-Za-z0-9_-]{43}$",
    )
    scanned_at: datetime

    model_config = {"extra": "forbid"}

    @field_validator("scanned_at")
    @classmethod
    def require_scan_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("scanned_at must include a timezone offset")
        return value


class AttendanceScanBatchRequest(BaseModel):
    batch_id: uuid.UUID
    scans: list[AttendanceScanBatchItemRequest] = Field(
        ...,
        min_length=1,
        max_length=ATTENDANCE_SCAN_BATCH_MAX_ITEMS,
    )

    model_config = {"extra": "forbid"}

    @model_validator(mode="after")
    def validate_unique_events_and_aggregate_size(self) -> AttendanceScanBatchRequest:
        event_ids = [scan.client_event_id for scan in self.scans]
        if len(event_ids) != len(set(event_ids)):
            raise ValueError("client_event_id values must be unique within a batch")
        aggregate_bytes = sum(
            len(scan.client_event_id.encode("utf-8"))
            + len(scan.qr_payload.encode("utf-8"))
            + len(scan.scanned_at.isoformat().encode("utf-8"))
            for scan in self.scans
        )
        if aggregate_bytes > ATTENDANCE_SCAN_BATCH_MAX_AGGREGATE_BYTES:
            raise ValueError("attendance scan batch exceeds the aggregate byte limit")
        return self


class AttendanceScanBatchItemResponse(BaseModel):
    client_event_id: str
    outcome: str = Field(..., pattern=r"^(counted|duplicate|rejected)$")
    retryable: bool
    scan: AttendanceScanResponse | None = None
    error_code: str | None = None

    @model_validator(mode="after")
    def validate_result_shape(self) -> AttendanceScanBatchItemResponse:
        if (self.scan is None) == (self.error_code is None):
            raise ValueError("Each batch item must contain exactly one of scan or error_code")
        return self


class AttendanceScanBatchResponse(BaseModel):
    batch_id: uuid.UUID
    items: list[AttendanceScanBatchItemResponse]


class AttendancePassengerStatus(BaseModel):
    passenger_id: uuid.UUID
    client_name: str
    client_email: str | None = None
    client_phone: str | None = None
    departure_city: str | None = None
    scanned: bool
    scanned_at: datetime | None = None


class AttendanceSessionDetailsResponse(BaseModel):
    id: uuid.UUID
    group_id: uuid.UUID
    name: str
    status: str
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    scanned_count: int
    assigned_count: int
    missing_passengers: list[AttendancePassengerStatus] = Field(default_factory=list)
    scanned_passengers: list[AttendancePassengerStatus] = Field(default_factory=list)
    passengers: list[AttendancePassengerStatus] = Field(default_factory=list)


class AttendanceCoordinatorSummary(BaseModel):
    coordinator_id: uuid.UUID
    coordinator_name: str
    assigned_count: int
    scanned_count: int


class AttendanceMissingPassenger(BaseModel):
    passenger_id: uuid.UUID
    client_name: str
    client_email: str | None = None
    client_phone: str | None = None
    departure_city: str | None = None
    coordinator_id: uuid.UUID | None = None
    coordinator_name: str | None = None


class AttendanceSessionSummary(BaseModel):
    id: uuid.UUID
    name: str
    status: str
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    assigned_count: int
    scanned_count: int
    coordinators: list[AttendanceCoordinatorSummary] = Field(default_factory=list)
    missing_passengers: list[AttendanceMissingPassenger] = Field(default_factory=list)
    closeout: AttendanceCloseoutStatusResponse


class GroupAttendanceOverviewResponse(BaseModel):
    group_id: uuid.UUID
    group_name: str
    sessions: list[AttendanceSessionSummary] = Field(default_factory=list)


class AttendanceSummaryCloseout(BaseModel):
    ready: bool
    active_participant_count: int = Field(ge=0)
    ready_participant_count: int = Field(ge=0)
    blocked_participant_count: int = Field(ge=0)
    missing_participant_count: int = Field(ge=0)
    stale_participant_count: int = Field(ge=0)
    unresolved_count: int = Field(ge=0)


class AttendanceCoordinatorActivitySummaryResponse(BaseModel):
    coordinator_id: uuid.UUID
    coordinator_name: str = Field(min_length=1, max_length=255)
    assigned_count: int = Field(ge=0)
    scanned_count: int = Field(ge=0)
    checkpoint_state: Literal["ready", "missing", "stale", "blocked"]
    checkpoint_reported_at: datetime | None = None
    pending_count: int = Field(ge=0)
    sending_count: int = Field(ge=0)
    retryable_count: int = Field(ge=0)
    needs_review_count: int = Field(ge=0)
    unreviewed_rejected_count: int = Field(ge=0)
    oldest_pending_age_seconds: int | None = Field(default=None, ge=0)
    runtime_count: int = Field(ge=1)
    active_runtime_count: int = Field(ge=0)


class AttendanceActivitySummaryResponse(BaseModel):
    id: uuid.UUID
    name: str
    status: str
    revision: str = Field(min_length=32, max_length=32, pattern="^[0-9a-f]+$")
    present_count: int = Field(ge=0)
    missing_count: int = Field(ge=0)
    exception_count: int = Field(ge=0)
    closeout: AttendanceSummaryCloseout
    coordinator_count: int = Field(default=0, ge=0)
    coordinators_truncated: bool = False
    coordinators: list[AttendanceCoordinatorActivitySummaryResponse] = Field(
        default_factory=list,
        max_length=25,
    )
    last_canonical_update_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None


class GroupAttendanceSummaryResponse(BaseModel):
    group_id: uuid.UUID
    group_name: str
    revision: str = Field(min_length=32, max_length=32, pattern="^[0-9a-f]+$")
    sessions: list[AttendanceActivitySummaryResponse] = Field(default_factory=list)


class AttendanceMissingPassengerItem(BaseModel):
    passenger_id: uuid.UUID
    display_name: str = Field(min_length=1, max_length=255)


class AttendanceMissingPassengersPageResponse(BaseModel):
    session_id: uuid.UUID
    revision: str = Field(min_length=32, max_length=32, pattern="^[0-9a-f]+$")
    items: list[AttendanceMissingPassengerItem] = Field(default_factory=list)
    has_more: bool
    next_cursor: uuid.UUID | None = None
    page_size: int = Field(ge=1, le=100)
