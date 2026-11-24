"""Focused passport bulk API contracts."""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ExportSelectedPassportsRequest(BaseModel):
    submission_ids: list[uuid.UUID] = Field(..., min_length=1, max_length=1500)


class ExportSelectedPassportImagesRequest(BaseModel):
    """Bound the synchronous ZIP path independently from lightweight exports."""

    model_config = ConfigDict(extra="forbid")

    submission_ids: list[uuid.UUID] = Field(..., min_length=1, max_length=500)


class BulkDocumentFollowUpRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    submission_ids: list[uuid.UUID] = Field(min_length=1, max_length=1500)
    flagged: bool


class BulkDocumentFollowUpResponse(BaseModel):
    updated_count: int = Field(ge=0)
    flagged: bool


class BulkDeletePassportSubmissionsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    submission_ids: list[uuid.UUID] = Field(..., min_length=1, max_length=1500)


class BulkDeletePassportSubmissionsResponse(BaseModel):
    deleted_count: int
    deleted_submission_ids: list[uuid.UUID]
    deleted_storage_objects: int
    deleted_notifications: int
    storage_cleanup_deferred: bool


class BulkStaffApprovePassportSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    submission_id: uuid.UUID
    expected_extraction_revision: int = Field(ge=0)


class BulkStaffApprovePassportSubmissionsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    submissions: list[BulkStaffApprovePassportSelection] = Field(
        ...,
        min_length=1,
        max_length=1500,
    )


class BulkStaffApproveSkippedSubmission(BaseModel):
    model_config = ConfigDict(extra="forbid")

    submission_id: uuid.UUID
    current_status: str
    reason: Literal["not_completed", "stale"]
    expected_extraction_revision: int = Field(ge=0)
    current_extraction_revision: int = Field(ge=0)


class BulkStaffApprovePassportSubmissionsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requested_count: int = Field(ge=1)
    approved_count: int = Field(ge=0)
    already_approved_count: int = Field(ge=0)
    skipped_count: int = Field(ge=0)
    approved_submission_ids: list[uuid.UUID] = Field(default_factory=list)
    already_approved_submission_ids: list[uuid.UUID] = Field(default_factory=list)
    skipped_submissions: list[BulkStaffApproveSkippedSubmission] = Field(default_factory=list)


class ExportSelectedGroupsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    group_ids: list[uuid.UUID] = Field(..., min_length=1, max_length=100)
    supplemental_fields: list[str] = Field(default_factory=list, max_length=256)
    group_by_field: str | None = Field(default=None, max_length=180)
