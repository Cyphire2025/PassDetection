"""Stdlib-only privacy projection shared by runtime and operator log collection."""

from __future__ import annotations

import json
import math
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ALLOWLISTS = json.loads(
    (Path(__file__).parents[1] / "config/mcp_diagnostic_allowlists.json").read_text("utf-8")
)
_EVENTS = frozenset(ALLOWLISTS["log_events"])
_LEVELS = frozenset({"debug", "info", "warning", "error", "critical"})
_ERROR_TYPES = frozenset(
    {
        "Error",
        "TypeError",
        "RangeError",
        "Unknown",
        "ValueError",
        "TimeoutError",
        "ConnectionError",
        "RuntimeError",
        "OSError",
    }
)


def diagnostic_identifier(value: Any) -> str | None:
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, TypeError, AttributeError):
        return None


def diagnostic_timestamp(value: Any) -> datetime | None:
    try:
        result = datetime.fromisoformat(value) if isinstance(value, str) else value
        return result.astimezone(UTC) if isinstance(result, datetime) and result.tzinfo else None
    except (ValueError, TypeError, OverflowError):
        return None


def project_diagnostic_record(record: dict[str, Any], timestamp: datetime) -> dict[str, Any]:
    event, level = record.get("event"), record.get("level")
    result: dict[str, Any] = {
        "timestamp": timestamp.isoformat(),
        "event": event if isinstance(event, str) and event in _EVENTS else "redacted_event",
        "content_trust": "untrusted_diagnostic_data",
    }
    if isinstance(level, str) and level in _LEVELS:
        result["level"] = level
    for key in (
        "request_id",
        "job_id",
        "event_id",
        "audit_id",
        "submission_id",
        "batch_id",
        "connection_id",
    ):
        if (value := diagnostic_identifier(record.get(key))) is not None:
            result[key] = value
    error_type = record.get("error_type", record.get("error_kind"))
    if isinstance(error_type, str) and error_type in _ERROR_TYPES:
        result["error_type"] = error_type
    status = record.get("status_code", record.get("status", record.get("http_status")))
    if isinstance(status, int) and not isinstance(status, bool) and 100 <= status <= 599:
        result["http_status"] = status
    duration = record.get("request_time", record.get("duration_seconds"))
    if (
        isinstance(duration, (float, int))
        and not isinstance(duration, bool)
        and 0 <= duration <= 86400
        and math.isfinite(duration)
    ):
        result["duration_seconds"] = duration
    return result
