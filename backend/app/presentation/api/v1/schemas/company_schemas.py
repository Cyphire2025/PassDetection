"""Allowlisted company contracts; no document or identity data in lookup."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class CompanyLookupResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")
    id: uuid.UUID
    name: str
    status: Literal["active", "inactive"]


class CompanyResponse(CompanyLookupResponse):
    external_reference: str | None
    revision: int
    created_at: datetime
    updated_at: datetime


class CompanyPageResponse(BaseModel):
    items: list[CompanyResponse]
    next_cursor: str | None
    has_more: bool


class CompanyLookupPageResponse(BaseModel):
    items: list[CompanyLookupResponse]
    next_cursor: str | None
    has_more: bool


class CompanyCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=255)
    external_reference: str | None = Field(default=None, max_length=128)

    @field_validator("external_reference")
    @classmethod
    def empty_reference(cls, value: str | None) -> str | None:
        return value or None


class CompanyUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    expected_revision: int = Field(ge=1)
    name: str | None = Field(default=None, min_length=1, max_length=255)
    external_reference: str | None = Field(default=None, max_length=128)
    status: Literal["active", "inactive"] | None = None


class CompanyAssignmentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    company_id: uuid.UUID
    expected_revision: int = Field(ge=0)


class CompanySummaryResponse(BaseModel):
    active_groups: int
    closed_groups: int
    archived_groups: int
    total_groups: int
    unique_travellers: int | None = None
    trip_participations: int | None = None
    unresolved_historical_records: int
    identity_totals_partial: bool = True


class CompanyGroupResponse(BaseModel):
    id: uuid.UUID
    name: str
    destination: str | None
    travel_date: date | None
    return_date: date | None
    status: Literal["active", "closed", "archived"]
    import_only: bool
    submission_count: int
    returning_travellers: int = 0
    trip_participations: int = 0
    reuse_completed: int = 0
    company_id: uuid.UUID
    company_revision: int


class CompanyGroupPageResponse(BaseModel):
    items: list[CompanyGroupResponse]
    next_cursor: str | None
    has_more: bool
