"""Stable tour contracts and bounded scan commands.

Scan validators retain this module as their call-time limit namespace; other
cohesive contracts are re-exported through their existing import paths.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field, field_validator, model_validator

from app.presentation.api.v1.schemas.attendance_closeout_schemas import (
    AttendanceCloseoutStatusResponse as AttendanceCloseoutStatusResponse,
)

from .tour_activity_schemas import AttendanceSessionResponse as AttendanceSessionResponse
from .tour_activity_schemas import CreateAttendanceSessionRequest as CreateAttendanceSessionRequest
from .tour_activity_schemas import (
    UpdateAttendanceScheduleRequest as UpdateAttendanceScheduleRequest,
)
from .tour_activity_schemas import _validate_attendance_schedule as _validate_attendance_schedule
from .tour_attendance_projection_schemas import (
    AttendanceActivitySummaryResponse as AttendanceActivitySummaryResponse,
)
from .tour_attendance_projection_schemas import (
    AttendanceCoordinatorActivitySummaryResponse as AttendanceCoordinatorActivitySummaryResponse,
)
from .tour_attendance_projection_schemas import (
    AttendanceCoordinatorSummary as AttendanceCoordinatorSummary,
)
from .tour_attendance_projection_schemas import (
    AttendanceMissingPassenger as AttendanceMissingPassenger,
)
from .tour_attendance_projection_schemas import (
    AttendanceMissingPassengerItem as AttendanceMissingPassengerItem,
)
from .tour_attendance_projection_schemas import (
    AttendanceMissingPassengersPageResponse as AttendanceMissingPassengersPageResponse,
)
from .tour_attendance_projection_schemas import (
    AttendancePassengerStatus as AttendancePassengerStatus,
)
from .tour_attendance_projection_schemas import (
    AttendanceSessionDetailsResponse as AttendanceSessionDetailsResponse,
)
from .tour_attendance_projection_schemas import AttendanceSessionSummary as AttendanceSessionSummary
from .tour_attendance_projection_schemas import (
    AttendanceSummaryCloseout as AttendanceSummaryCloseout,
)
from .tour_attendance_projection_schemas import (
    GroupAttendanceOverviewResponse as GroupAttendanceOverviewResponse,
)
from .tour_attendance_projection_schemas import (
    GroupAttendanceSummaryResponse as GroupAttendanceSummaryResponse,
)
from .tour_coordinator_schemas import (
    AssignedPassengerDetailResponse as AssignedPassengerDetailResponse,
)
from .tour_coordinator_schemas import AssignedPassengerResponse as AssignedPassengerResponse
from .tour_coordinator_schemas import (
    AssignGroupCoordinatorsRequest as AssignGroupCoordinatorsRequest,
)
from .tour_coordinator_schemas import AssignGroupPassengersRequest as AssignGroupPassengersRequest
from .tour_coordinator_schemas import CoordinatorResponse as CoordinatorResponse
from .tour_coordinator_schemas import CreateCoordinatorRequest as CreateCoordinatorRequest
from .tour_coordinator_schemas import (
    GroupCoordinatorAssignmentResponse as GroupCoordinatorAssignmentResponse,
)
from .tour_coordinator_schemas import (
    TourOperationsArchitectureResponse as TourOperationsArchitectureResponse,
)
from .tour_coordinator_schemas import TourOperationsGroupResponse as TourOperationsGroupResponse
from .tour_coordinator_schemas import TourOperationsPhaseResponse as TourOperationsPhaseResponse
from .tour_qr_schemas import GroupPassengerQrCodeResponse as GroupPassengerQrCodeResponse
from .tour_qr_schemas import GroupPassengerQrCodesResponse as GroupPassengerQrCodesResponse
from .tour_qr_schemas import PassengerQrTokenResponse as PassengerQrTokenResponse
from .tour_qr_schemas import QrDeliveryPreviewRecipient as QrDeliveryPreviewRecipient
from .tour_qr_schemas import QrDeliveryPreviewResponse as QrDeliveryPreviewResponse
from .tour_qr_schemas import QrDeliveryPreviewSummary as QrDeliveryPreviewSummary
from .tour_qr_schemas import SendQrBroadcastRequest as SendQrBroadcastRequest
from .tour_qr_schemas import SendQrBroadcastResponse as SendQrBroadcastResponse
from .tour_qr_schemas import SetPassengerQrActiveRequest as SetPassengerQrActiveRequest
from .tour_qr_schemas import SetPassengerQrExpirationRequest as SetPassengerQrExpirationRequest


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
