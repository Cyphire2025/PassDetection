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
    source: str = "manual"
    delivery_status: str = "not_sent"
    sent_to: str | None = None
    last_sent_at: datetime | None = None
    can_resend: bool = False
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


class DocumentDeliveryPreviewRecipient(BaseModel):
    passenger_id: uuid.UUID
    passenger_name: str
    passport_number: str | None = None
    document_id: uuid.UUID | None = None
    document_filename: str | None = None
    document_type: str
    recipient_id: uuid.UUID | None = None
    broadcast_group_id: uuid.UUID | None = None
    broadcast_name: str | None = None
    phone_number: str | None = None
    delivery_id: uuid.UUID | None = None
    delivery_status: str
    eligible: bool = False
    resend_allowed: bool = False
    reason: str
    error_message: str | None = None
    message_preview: str | None = None


class DocumentDeliveryPreviewSummary(BaseModel):
    total_passengers: int = 0
    ready: int = 0
    retryable: int = 0
    already_sent: int = 0
    in_progress: int = 0
    blocked: int = 0


class DocumentDeliveryPreviewResponse(BaseModel):
    group_id: uuid.UUID
    batch_id: uuid.UUID
    document_type: str
    template_name: str | None = None
    template_configured: bool = False
    linked_broadcast_count: int = 0
    can_send: bool = False
    configuration_error: str | None = None
    message_content_1: str
    message_content_2: str
    summary: DocumentDeliveryPreviewSummary
    recipients: list[DocumentDeliveryPreviewRecipient] = Field(default_factory=list)


class SendDocumentBroadcastRequest(BaseModel):
    document_ids: list[uuid.UUID] | None = Field(default=None, max_length=500)
    resend_document_ids: list[uuid.UUID] = Field(default_factory=list, max_length=500)
    message_content_1: str = Field(min_length=1, max_length=600)
    message_content_2: str = Field(min_length=1, max_length=600)


class SendDocumentBroadcastResponse(BaseModel):
    send_batch_id: uuid.UUID | None = None
    queued_count: int = 0
    skipped_count: int = 0
    message: str


class DocumentDeliveryTrackingCounts(BaseModel):
    total: int = 0
    queued: int = 0
    sent: int = 0
    delivered: int = 0
    read: int = 0
    failed: int = 0
    delivery_unknown: int = 0


class DocumentDeliveryTrackingRow(BaseModel):
    delivery_id: uuid.UUID
    passenger_id: uuid.UUID | None = None
    passenger_name: str
    passport_number: str | None = None
    document_type: str
    document_filename: str
    phone_number: str
    status: str
    error_message: str | None = None
    status_updated_at: datetime


class DocumentDeliveryTrackingResponse(BaseModel):
    group_id: uuid.UUID
    counts: DocumentDeliveryTrackingCounts
    deliveries: list[DocumentDeliveryTrackingRow] = Field(default_factory=list)
