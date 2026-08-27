"""Bounded audit-ledger response contracts."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

AuditLogResult = Literal["success", "blocked", "denied", "failed"]


class AuditLogListItemResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    agency_id: uuid.UUID | None = None
    user_id: uuid.UUID | None = None
    actor_email: str | None = None
    event_type: str
    entity_type: str
    entity_id: str | None = None
    result: AuditLogResult | None = None
    created_at: datetime


class AuditLogPageResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[AuditLogListItemResponse] = Field(default_factory=list)
    has_more: bool
    next_cursor: str | None = None
    incomplete: bool
    page_size: int = Field(ge=1, le=100)


__all__ = ["AuditLogListItemResponse", "AuditLogPageResponse", "AuditLogResult"]
