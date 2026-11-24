"""Focused passport export API contracts."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class PassportExportHistoryItemResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    export_kind: Literal["passport_images", "passport_excel"]
    export_mode: Literal["all", "incremental"]
    baseline_export_id: uuid.UUID | None = None
    total_available_count: int = Field(ge=0)
    exported_count: int = Field(ge=0)
    pending_recipient_count: int = Field(default=0, ge=0)
    new_submission_count: int = Field(default=0, ge=0)
    changed_submission_count: int = Field(default=0, ge=0)
    removed_submission_count: int = Field(default=0, ge=0)
    compatible: bool = True
    actor_email: str | None = None
    created_at: datetime
    completed_at: datetime


class PassportExportHistoryListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    group_id: uuid.UUID
    export_kind: Literal["passport_images", "passport_excel"]
    current_submission_count: int = Field(ge=0)
    items: list[PassportExportHistoryItemResponse] = Field(default_factory=list)
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=100)
    total_count: int = Field(ge=0)
    total_pages: int = Field(ge=0)


class PassportExportHistorySubmissionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    submission_id: uuid.UUID
    record_available: bool = True
    client_name: str | None = None
    client_phone: str | None = None
    client_email: str | None = None
    passport_number: str | None = None


class PassportExportHistoryDetailResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    history_id: uuid.UUID
    group_id: uuid.UUID
    export_kind: Literal["passport_images", "passport_excel"]
    created_at: datetime
    completed_at: datetime
    exported_count: int = Field(ge=0)
    items: list[PassportExportHistorySubmissionResponse] = Field(default_factory=list)
    page: int = Field(ge=1)
    page_size: int = Field(ge=1)
    total_pages: int = Field(ge=0)


class PassportExportHistoryCompletionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    history_id: uuid.UUID
    group_id: uuid.UUID
    export_kind: Literal["passport_images", "passport_excel"]
    status: Literal["completed"]
    completed_at: datetime


class PassportExportFieldOptionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(..., min_length=1, max_length=180)
    label: str = Field(..., min_length=1, max_length=120)
    source: Literal["whatsapp"]
    selected_by_default: bool = False


class PassportExportGroupingOptionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(..., min_length=1, max_length=180)
    label: str = Field(..., min_length=1, max_length=120)
    fixed: bool = False


class PassportExportFieldOptionsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    group_id: uuid.UUID
    fields: list[PassportExportFieldOptionResponse] = Field(default_factory=list)
    agency_match_enabled: bool = False
    agency_match_fields: list[PassportExportFieldOptionResponse] = Field(default_factory=list)
    grouping_fields: list[PassportExportGroupingOptionResponse] = Field(default_factory=list)
    default_selected_fields: list[str] = Field(default_factory=list)
    default_group_by_field: str | None = None


class PassportSelectedGroupsExportFieldOptionsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    group_ids: list[uuid.UUID] = Field(..., min_length=1, max_length=100)
    fields: list[PassportExportFieldOptionResponse] = Field(default_factory=list)
    grouping_fields: list[PassportExportGroupingOptionResponse] = Field(default_factory=list)
    default_selected_fields: list[str] = Field(default_factory=list)
    default_group_by_field: str | None = None
