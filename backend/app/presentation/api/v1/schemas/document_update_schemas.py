"""Text-only updates have a separate audience and ledger from PDF delivery."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class DocumentUpdateRecipient(BaseModel):
    passenger_id: uuid.UUID
    passenger_name: str
    phone_number: str | None = None
    recipient_id: uuid.UUID | None = None
    broadcast_group_id: uuid.UUID | None = None
    document_count: int = 0
    confirmed_count: int = 0
    eligible: bool = False
    reason: str | None = None
    latest_update_status: str | None = None
    latest_update_error: str | None = None
    latest_update_at: datetime | None = None


class DocumentUpdatePreview(BaseModel):
    group_id: uuid.UUID
    document_type: str
    preview_token: str
    template_name: str
    template_language: str
    can_send: bool
    configuration_error: str | None = None
    recipients: list[DocumentUpdateRecipient]


class SendDocumentUpdateRequest(BaseModel):
    request_id: uuid.UUID
    preview_token: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")
    passenger_ids: list[uuid.UUID] = Field(min_length=1, max_length=1500)
    message_content: str = Field(min_length=1, max_length=600)
    broadcast_group_id: uuid.UUID | None = None


class SendDocumentUpdateResponse(BaseModel):
    request_id: uuid.UUID
    queued_count: int
    passenger_count: int
    message: str
