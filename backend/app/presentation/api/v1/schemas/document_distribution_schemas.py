"""Document distribution API schemas."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class DocumentGroupResponse(BaseModel):
    group_id: uuid.UUID
    group_name: str
    group_status: str
    destination: str | None = None
    travel_date: str | None = None
    total_passengers: int


class RejectedDocumentResponse(BaseModel):
    filename: str
    detected_type: str
    reason: str


class VerifiedDocumentResponse(BaseModel):
    filename: str
    detected_type: str
    accepted: bool
    reason: str
    matched_passenger_id: uuid.UUID | None = None
    matched_passenger_name: str | None = None
    matched_passenger_ids: list[uuid.UUID] = Field(default_factory=list)
    matched_passenger_names: list[str] = Field(default_factory=list)
    match_confidence: float = 0.0
    match_status: str | None = None
    match_reason: str | None = None


class VerifyDocumentBatchResponse(BaseModel):
    group_id: uuid.UUID
    document_type: str
    total_count: int
    accepted_count: int
    rejected_count: int
    files: list[VerifiedDocumentResponse] = Field(default_factory=list)


class DistributedDocumentResponse(BaseModel):
    id: uuid.UUID
    original_filename: str
    document_type: str
    detected_type: str
    match_status: str
    match_confidence: float
    match_reason: str | None = None
    extracted_name: str | None = None
    extracted_passport_number: str | None = None
    extracted_reference: str | None = None
    url: str | None = None


class DocumentPassengerReviewRow(BaseModel):
    passenger_id: uuid.UUID
    passenger_name: str
    passport_number: str | None = None
    departure_city: str | None = None
    document: DistributedDocumentResponse | None = None


class DocumentBatchResponse(BaseModel):
    batch_id: uuid.UUID | None = None
    group_id: uuid.UUID
    document_type: str
    status: str = "draft"
    uploaded_count: int = 0
    rejected_count: int = 0
    matched_count: int = 0
    saved_at: datetime | None = None
    created_at: datetime | None = None
    review_rows: list[DocumentPassengerReviewRow] = Field(default_factory=list)
    unmatched_documents: list[DistributedDocumentResponse] = Field(default_factory=list)
    rejected_documents: list[RejectedDocumentResponse] = Field(default_factory=list)


class DeleteDistributionDocumentsRequest(BaseModel):
    document_ids: list[uuid.UUID] = Field(default_factory=list)


class SaveDocumentBatchResponse(BaseModel):
    batch_id: uuid.UUID
    status: str
    saved_at: datetime
