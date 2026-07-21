"""
Tour Operations API Schemas
===========================
Phase 1 exposes module architecture and implementation status only.
Workflow endpoints are added in later phases.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, EmailStr, Field, field_validator


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


class AttendanceSessionResponse(BaseModel):
    id: uuid.UUID
    group_id: uuid.UUID
    name: str
    status: str
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    scanned_count: int = 0
    assigned_count: int = 0


class AttendanceScanRequest(BaseModel):
    qr_payload: str = Field(..., min_length=49, max_length=49, pattern=r"^pdatt:[A-Za-z0-9_-]{43}$")
    client_event_id: str = Field(..., min_length=8, max_length=128, pattern=r"^[A-Za-z0-9:_-]+$")
    scanned_at: datetime | None = None
    device_id: str | None = Field(default=None, max_length=128, pattern=r"^[A-Za-z0-9:_-]+$")
    sync_source: str = Field(default="online", pattern="^(online|offline)$")


class AttendanceScanResponse(BaseModel):
    session_id: uuid.UUID
    passenger_id: uuid.UUID | None = None
    passenger_name: str | None = None
    status: str
    message: str
    scanned_count: int
    assigned_count: int


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
    coordinator_id: uuid.UUID
    coordinator_name: str


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


class GroupAttendanceOverviewResponse(BaseModel):
    group_id: uuid.UUID
    group_name: str
    sessions: list[AttendanceSessionSummary] = Field(default_factory=list)
