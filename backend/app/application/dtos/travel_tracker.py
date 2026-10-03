"""Bounded tracker contracts shared by the dashboard and MCP tools."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

TrackerTrack = Literal["visa", "flight"]
TrackerStatus = Literal["all", "marked", "pending"]


class TrackerGroup(BaseModel):
    id: uuid.UUID
    name: str
    destination: str | None
    travel_date: date | None
    return_date: date | None
    status: str
    total: int
    visa_marked: int
    flight_marked: int


class TrackerGroupList(BaseModel):
    groups: list[TrackerGroup]
    total: int
    page: int
    page_size: int


class TrackerCounts(BaseModel):
    total: int
    marked: int
    pending: int


class TrackerPassenger(BaseModel):
    id: uuid.UUID
    full_name: str
    given_name: str | None
    surname: str | None
    passport_number: str | None
    nationality: str | None
    gender: str | None
    date_of_birth: str | None
    date_of_expiry: str | None
    email: str | None
    phone: str | None
    departure_city: str | None
    submission_status: str
    visa_applied: bool
    flight_booked: bool
    visa_updated_at: datetime | None
    flight_updated_at: datetime | None


class TrackerWorkspace(BaseModel):
    group: TrackerGroup
    counts: TrackerCounts
    passengers: list[TrackerPassenger]
    total: int
    page: int
    page_size: int


class TrackerSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: TrackerStatus = "all"
    search: str | None = Field(default=None, max_length=160)


class TrackerMarkRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    track: TrackerTrack
    marked: bool = Field(strict=True)
    passenger_ids: list[uuid.UUID] | None = Field(default=None, min_length=1, max_length=1000)
    selection: TrackerSelection | None = None
    expected_count: int | None = Field(default=None, ge=0, le=20000)

    @model_validator(mode="after")
    def validate_selection(self) -> TrackerMarkRequest:
        if (self.passenger_ids is None) == (self.selection is None):
            raise ValueError("Supply either passenger_ids or a filtered selection")
        if self.selection is not None and self.expected_count is None:
            raise ValueError("Filtered selection requires expected_count")
        if self.passenger_ids is not None and self.expected_count is not None:
            raise ValueError("expected_count is only valid for a filtered selection")
        return self


class TrackerMarkResponse(BaseModel):
    updated_count: int
    unchanged_count: int
    passenger_ids: list[uuid.UUID]
    counts: TrackerCounts


class TrackerImportRow(BaseModel):
    row_number: int
    name: str | None = None
    passport_number: str | None = None
    passenger_id: uuid.UUID | None = None
    passenger_name: str | None = None
    status: Literal["matched", "ambiguous", "unmatched", "duplicate"]
    reason: str


class TrackerImportPreview(BaseModel):
    track: TrackerTrack
    marked: bool
    total_rows: int
    matched_count: int
    ambiguous_count: int
    unmatched_count: int
    duplicate_count: int
    passenger_ids: list[uuid.UUID]
    rows: list[TrackerImportRow]
