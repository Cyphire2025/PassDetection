"""Typed audit query, pagination and integrity outcomes."""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from app.infrastructure.database.models import AuditLogModel
from app.infrastructure.repositories.audit_log_values import _cursor_value

AuditResult = Literal["success", "blocked", "denied", "failed"]


@dataclass(frozen=True, slots=True)
class AuditLogFilters:
    agency_id: uuid.UUID | None
    start_at: datetime | None = None
    end_at: datetime | None = None
    actor: str | None = None
    event_type: str | None = None
    entity_type: str | None = None
    entity_id: str | None = None
    result: AuditResult | None = None

    def fingerprint(self) -> str:
        values = (
            self.agency_id,
            self.start_at,
            self.end_at,
            self.actor,
            self.event_type,
            self.entity_type,
            self.entity_id,
            self.result,
        )
        encoded = "|".join(_cursor_value(value) for value in values)
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:24]


@dataclass(frozen=True, slots=True)
class AuditLogPage:
    items: tuple[AuditLogModel, ...]
    has_more: bool
    next_cursor: str | None


@dataclass(frozen=True, slots=True)
class AuditChainVerification:
    scope_key: str
    valid: bool
    verified_entries: int
    first_invalid_sequence: int | None
    reason: str | None


@dataclass(frozen=True, slots=True)
class _AuditCursor:
    last_created_at: datetime
    last_id: uuid.UUID
    snapshot_created_at: datetime
    snapshot_id: uuid.UUID
    filter_fingerprint: str


class InvalidAuditCursorError(ValueError):
    """A cursor is malformed or belongs to a different filter scope."""
