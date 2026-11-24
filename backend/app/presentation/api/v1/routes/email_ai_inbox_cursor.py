"""Opaque pagination cursors for the email inbox's stable sort order."""

from __future__ import annotations

import base64
import json
import uuid
from datetime import UTC, datetime

from fastapi import HTTPException, status


def _priority_rank(priority: str | None) -> int:
    return {"urgent": 0, "high": 1, "normal": 2}.get(priority or "", 3)


def _encode_cursor(
    priority: str | None,
    updated_at: datetime,
    analysis_id: uuid.UUID,
) -> str:
    if updated_at.tzinfo is None:
        updated_at = updated_at.replace(tzinfo=UTC)
    payload = json.dumps(
        {
            "priority_rank": _priority_rank(priority),
            "updated_at": updated_at.isoformat(),
            "id": str(analysis_id),
        },
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def _decode_cursor(value: str) -> tuple[int, datetime, uuid.UUID]:
    try:
        padding = "=" * (-len(value) % 4)
        payload = json.loads(base64.urlsafe_b64decode(value + padding))
        priority_rank = int(payload["priority_rank"])
        updated_at = datetime.fromisoformat(payload["updated_at"])
        analysis_id = uuid.UUID(payload["id"])
        if priority_rank not in {0, 1, 2, 3} or updated_at.tzinfo is None:
            raise ValueError
        return priority_rank, updated_at, analysis_id
    except (KeyError, TypeError, ValueError, OverflowError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Invalid inbox cursor.",
        ) from exc
