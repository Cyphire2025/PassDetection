"""Cross-workspace WhatsApp broadcast activity contracts."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

WhatsAppActivityKind = Literal["broadcast", "document", "qr"]
DocumentActivityStatusFilter = Literal[
    "all", "queued", "processing", "sent", "delivered", "read", "failed", "needs_review",
]


class WhatsAppActivitySummaryResponse(BaseModel):
    """Compact live progress for one durable WhatsApp send batch."""

    activity_id: uuid.UUID
    kind: WhatsAppActivityKind
    title: str
    context_label: str
    source_group_id: uuid.UUID
    document_type: str | None = None
    total: int
    queued: int
    sent: int
    failed: int
    delivery_unknown: int
    status_counts: dict[str, int] = Field(default_factory=dict)
    started_at: datetime
    updated_at: datetime


class WhatsAppActivityFailureResponse(BaseModel):
    """One failed destination revealed on demand by the progress UI."""

    recipient_name: str
    phone_number: str
    error_message: str | None = None


class DocumentActivityDeliveryResponse(BaseModel):
    """One frozen document destination, including its current delivery result."""

    delivery_id: uuid.UUID
    passenger_name: str
    phone_number: str
    document_filename: str
    document_type: str
    status: str
    error_message: str | None = None
    status_updated_at: datetime


class DocumentActivityDeliveriesResponse(BaseModel):
    """A bounded page of document deliveries matching the requested filters."""

    items: list[DocumentActivityDeliveryResponse]
    total: int
    offset: int
    limit: int
