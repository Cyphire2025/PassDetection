"""Bounded, per-send delivery history for the broadcast workspace."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel

HistoryFilter = Literal["all", "sent", "not_sent", "delivery_left", "failed"]


class MessageHistoryCounts(BaseModel):
    all: int = 0
    sent: int = 0
    not_sent: int = 0
    delivery_left: int = 0
    failed: int = 0


class MessageHistoryEntry(BaseModel):
    id: UUID
    message_type: str
    message_preview: str
    rendered_message: str | None = None
    created_at: datetime
    updated_at: datetime
    counts: MessageHistoryCounts


class MessageHistoryPage(BaseModel):
    items: list[MessageHistoryEntry]
    total: int
    offset: int
    limit: int


class MessageHistoryRecipient(BaseModel):
    message_log_id: UUID
    recipient_id: UUID
    name: str | None
    phone_number: str
    current_phone_number: str
    status: str
    error_message: str | None
    rendered_message: str | None
    updated_at: datetime
    removed: bool
    can_resend: bool


class MessageHistoryRecipientPage(BaseModel):
    items: list[MessageHistoryRecipient]
    total: int
    offset: int
    limit: int
    counts: MessageHistoryCounts
