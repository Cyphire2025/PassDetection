"""Document rename API schemas."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class RenameDocumentItemResponse(BaseModel):
    id: uuid.UUID
    original_filename: str
    renamed_filename: str
    detected_type: str
    extracted_name: str | None = None
    extracted_passport_number: str | None = None
    extracted_reference: str | None = None
    status: str
    reason: str | None = None
    download_url: str


class RenameDocumentBatchResponse(BaseModel):
    batch_id: uuid.UUID
    title: str
    status: str
    total_count: int
    visa_count: int
    ticket_count: int
    unknown_count: int
    zip_download_url: str
    created_at: datetime
    items: list[RenameDocumentItemResponse] = Field(default_factory=list)


class RenameDocumentBatchSummaryResponse(BaseModel):
    batch_id: uuid.UUID
    title: str
    status: str
    total_count: int
    visa_count: int
    ticket_count: int
    unknown_count: int
    zip_download_url: str
    created_at: datetime


class DeleteRenameBatchesRequest(BaseModel):
    batch_ids: list[uuid.UUID] = Field(min_length=1)


class DeleteRenameBatchesResponse(BaseModel):
    deleted_count: int
    deleted_storage_objects: int
