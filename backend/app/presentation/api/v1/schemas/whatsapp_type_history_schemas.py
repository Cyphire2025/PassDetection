"""Recipient-level type coverage and immutable, separately numbered sends."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.presentation.api.v1.schemas.whatsapp_history_schemas import (
    MessageHistoryCounts,
    MessageHistoryEntry,
)


class MessageTypeSummary(BaseModel):
    message_type: str
    counts: MessageHistoryCounts
    never_attempted: int
    send_count: int
    version_count: int
    legacy_record_count: int
    total_attempts: int
    accepted_attempts: int
    last_sent_at: datetime | None


class MessageTypeVersion(MessageHistoryEntry):
    version_number: int | None


class MessageTypeVersionPage(BaseModel):
    items: list[MessageTypeVersion]
    total: int
    offset: int
    limit: int


class MessageTypeRecipient(BaseModel):
    recipient_id: UUID
    name: str | None
    phone_number: str
    status: str
    message_id: UUID | None
    message_log_id: UUID | None
    updated_at: datetime | None
    error_message: str | None


class MessageTypeRecipientPage(BaseModel):
    items: list[MessageTypeRecipient]
    total: int
    offset: int
    limit: int
    counts: MessageHistoryCounts
