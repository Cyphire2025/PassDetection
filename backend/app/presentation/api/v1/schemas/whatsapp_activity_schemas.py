"""Cross-workspace WhatsApp broadcast activity contracts."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel

WhatsAppActivityKind = Literal["broadcast", "document", "qr"]


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
    started_at: datetime
    updated_at: datetime


class WhatsAppActivityFailureResponse(BaseModel):
    """One failed destination revealed on demand by the progress UI."""

    recipient_name: str
    phone_number: str
    error_message: str | None = None
