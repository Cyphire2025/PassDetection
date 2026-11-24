"""Focused passport document API contracts."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class ImportPassportGroupResponse(BaseModel):
    imported_count: int
    updated_count: int = 0
    skipped_count: int


class PassportDocumentImportItem(BaseModel):
    filename: str
    staff_code: str | None = None
    document_type: str | None = None
    passenger_id: uuid.UUID | None = None
    passenger_name: str | None = None
    accepted: bool
    reason: str | None = None


class PassportDocumentImportPreviewResponse(BaseModel):
    group_id: uuid.UUID
    total_count: int
    accepted_count: int
    rejected_count: int
    accepted_documents: list[PassportDocumentImportItem] = Field(default_factory=list)
    rejected_documents: list[PassportDocumentImportItem] = Field(default_factory=list)


class PassportDocumentImportSaveResponse(PassportDocumentImportPreviewResponse):
    saved_count: int


class PassengerQrStatusResponse(BaseModel):
    status: str
    token_version: int | None = None
    created_at: datetime | None = None
    expires_at: datetime | None = None
    revoked_at: datetime | None = None


class PassportExtractionConflictResponse(BaseModel):
    field: str
    manual_value: str
    extracted_value: str | None = None
    status: Literal["mismatch", "not_extracted"]
