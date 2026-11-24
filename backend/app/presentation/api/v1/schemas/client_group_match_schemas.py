"""Group matching, replacement and rejected-upload contracts."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class WhatsAppSubmissionMatchCountsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total_recipients: int = Field(ge=0)
    submitted_count: int = Field(ge=0)
    not_submitted_count: int = Field(ge=0)
    multiple_submission_count: int = Field(ge=0)
    matched_submission_count: int = Field(ge=0)
    needs_review_count: int = Field(default=0, ge=0)
    needs_review_submission_count: int = Field(default=0, ge=0)
    unmatched_submission_count: int = Field(default=0, ge=0)
    replacement_count: int = Field(default=0, ge=0)
    rejected_upload_count: int = Field(default=0, ge=0)


class WhatsAppSubmissionMatchEvidenceResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    submission_id: uuid.UUID
    kind: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9_]+$")
    recipient_value: str
    submission_value: str
    weight: int = Field(ge=0)


class WhatsAppRecipientImportedFieldsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recipient_id: uuid.UUID
    fields: dict[str, str] = Field(default_factory=dict)


class WhatsAppSubmissionDetailResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    submission_id: uuid.UUID
    name: str
    phone: str | None = None
    email: str | None = None
    fields: dict[str, object] = Field(default_factory=dict)


class WhatsAppSubmissionMatchRowResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal[
        "submitted",
        "not_submitted",
        "multiple_submissions",
        "needs_review",
        "unmatched_submission",
        "replacement",
        "rejected_upload",
    ]
    match_basis: str | None = None
    normalized_phone: str | None = None
    recipient_ids: list[uuid.UUID] = Field(default_factory=list)
    submission_ids: list[uuid.UUID] = Field(default_factory=list)
    broadcast_ids: list[uuid.UUID] = Field(default_factory=list)
    broadcast_names: list[str] = Field(default_factory=list)
    recipient_names: list[str] = Field(default_factory=list)
    submission_names: list[str] = Field(default_factory=list)
    confidence: Literal["high", "medium", "none"] = "none"
    match_evidence: list[WhatsAppSubmissionMatchEvidenceResponse] = Field(default_factory=list)
    candidate_submission_ids: list[uuid.UUID] = Field(default_factory=list)
    duplicate_submission_ids: list[uuid.UUID] = Field(default_factory=list)
    recipient_fields: list[WhatsAppRecipientImportedFieldsResponse] = Field(default_factory=list)
    submission_details: list[WhatsAppSubmissionDetailResponse] = Field(default_factory=list)
    resolution_id: uuid.UUID | None = None
    updated_at: datetime


class ClientGroupWhatsAppMatchesResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_group_id: uuid.UUID
    selected_broadcast_id: uuid.UUID | None = None
    linked_broadcast_count: int = Field(ge=0)
    counts: WhatsAppSubmissionMatchCountsResponse
    matches: list[WhatsAppSubmissionMatchRowResponse] = Field(default_factory=list)
    total: int = Field(ge=0)
    page: int = Field(ge=1)
    page_size: int = Field(ge=1)
    total_pages: int = Field(ge=0)


class ReplacementCandidateResponse(BaseModel):
    # This name collides with another schema; retain its published OpenAPI identity.
    __module__ = "app.presentation.api.v1.schemas.client_group_schemas"
    model_config = ConfigDict(extra="forbid")

    recipient_id: uuid.UUID
    recipient_ids: list[uuid.UUID] = Field(min_length=1)
    name: str | None = None
    phone: str
    broadcast_ids: list[uuid.UUID] = Field(default_factory=list)
    broadcast_names: list[str] = Field(default_factory=list)
    imported_fields: dict[str, str] = Field(default_factory=dict)


# Resolve its one external annotation without depending on the facade's import order.
ReplacementCandidateResponse.model_rebuild(_types_namespace={"uuid": uuid})


class ReplacementCandidateListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_group_id: uuid.UUID
    items: list[ReplacementCandidateResponse] = Field(default_factory=list)


class ResolveUnidentifiedReplacementRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recipient_id: uuid.UUID
    request_id: uuid.UUID


class RejectUnidentifiedUploadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: uuid.UUID


class PassportRosterResolutionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    client_group_id: uuid.UUID
    submission_id: uuid.UUID
    resolution_type: Literal["replacement", "rejected"]
    status: Literal["active", "restored"]
    broadcast_recipient_id: uuid.UUID | None = None
    suppressed_recipient_ids: list[uuid.UUID] = Field(default_factory=list)
    excluded_submission_ids: list[uuid.UUID] = Field(default_factory=list)
    created_at: datetime
    restored_at: datetime | None = None
