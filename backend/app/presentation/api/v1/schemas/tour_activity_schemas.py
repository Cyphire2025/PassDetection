"""Attendance activity creation, schedule validation and session summaries."""

from __future__ import annotations

import uuid
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, Field, field_validator, model_validator


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
