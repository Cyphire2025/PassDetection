"""Tenant-bound audit filters and stable keyset cursor encoding."""

from __future__ import annotations

import base64
import binascii
import json
import uuid
from datetime import datetime

from sqlalchemy.sql import Select

from app.infrastructure.database.models import AuditLogModel
from app.infrastructure.repositories.audit_log_types import (
    AuditLogFilters,
    InvalidAuditCursorError,
    _AuditCursor,
)
from app.infrastructure.repositories.audit_log_values import _escape_like, _require_aware, _utc


def _apply_filters(
    statement: Select[tuple[AuditLogModel]],
    filters: AuditLogFilters,
) -> Select[tuple[AuditLogModel]]:
    if filters.agency_id is not None:
        statement = statement.where(AuditLogModel.agency_id == filters.agency_id)
    if filters.start_at is not None:
        statement = statement.where(AuditLogModel.created_at >= filters.start_at)
    if filters.end_at is not None:
        statement = statement.where(AuditLogModel.created_at <= filters.end_at)
    if filters.actor:
        try:
            actor_id = uuid.UUID(filters.actor)
        except ValueError:
            statement = statement.where(
                AuditLogModel.actor_email.ilike(
                    f"%{_escape_like(filters.actor)}%",
                    escape="\\",
                )
            )
        else:
            statement = statement.where(AuditLogModel.user_id == actor_id)
    if filters.event_type:
        statement = statement.where(AuditLogModel.action == filters.event_type)
    if filters.entity_type:
        statement = statement.where(AuditLogModel.entity_type == filters.entity_type)
    if filters.entity_id:
        statement = statement.where(AuditLogModel.entity_id == filters.entity_id)
    if filters.result:
        statement = statement.where(AuditLogModel.result == filters.result)
    return statement


def _encode_cursor(cursor: _AuditCursor) -> str:
    payload = {
        "v": 1,
        "last_created_at": _utc(cursor.last_created_at).isoformat(),
        "last_id": str(cursor.last_id),
        "snapshot_created_at": _utc(cursor.snapshot_created_at).isoformat(),
        "snapshot_id": str(cursor.snapshot_id),
        "filters": cursor.filter_fingerprint,
    }
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_cursor(value: str) -> _AuditCursor:
    try:
        padding = "=" * (-len(value) % 4)
        raw = base64.b64decode(
            f"{value}{padding}",
            altchars=b"-_",
            validate=True,
        )
        payload = json.loads(raw.decode("utf-8"))
        if not isinstance(payload, dict) or payload.get("v") != 1:
            raise ValueError
        last_created_at = datetime.fromisoformat(str(payload["last_created_at"]))
        snapshot_created_at = datetime.fromisoformat(str(payload["snapshot_created_at"]))
        filter_fingerprint = str(payload["filters"])
        if len(filter_fingerprint) != 24:
            raise ValueError
        return _AuditCursor(
            last_created_at=_require_aware(last_created_at),
            last_id=uuid.UUID(str(payload["last_id"])),
            snapshot_created_at=_require_aware(snapshot_created_at),
            snapshot_id=uuid.UUID(str(payload["snapshot_id"])),
            filter_fingerprint=filter_fingerprint,
        )
    except (
        binascii.Error,
        KeyError,
        TypeError,
        UnicodeDecodeError,
        ValueError,
    ) as exc:
        raise InvalidAuditCursorError("Audit cursor is invalid") from exc
