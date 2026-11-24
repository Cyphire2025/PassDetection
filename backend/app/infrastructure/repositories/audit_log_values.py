"""Canonical audit metadata and cursor scalar normalization."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum
from math import isfinite


def _canonical_audit_value(value: object) -> object:
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        if not isfinite(value):
            raise ValueError("Audit metadata cannot contain non-finite numbers")
        return value
    if isinstance(value, datetime):
        return _utc(value).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, (uuid.UUID, Decimal)):
        return str(value)
    if isinstance(value, Enum):
        return _canonical_audit_value(value.value)
    if isinstance(value, dict):
        return {
            str(key): _canonical_audit_value(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_canonical_audit_value(item) for item in value]
    raise TypeError(f"Unsupported audit metadata value: {type(value).__name__}")


def _cursor_value(value: object) -> str:
    if isinstance(value, datetime):
        return _utc(value).isoformat()
    if value is None:
        return "-"
    return str(value)


def _require_aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Cursor timestamps must include a UTC offset")
    return value.astimezone(UTC)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
