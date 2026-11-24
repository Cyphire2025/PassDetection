"""UTC timestamps and random UUID factories shared by domain entities."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime


def _utcnow() -> datetime:
    return datetime.now(tz=UTC)


def _new_uuid() -> uuid.UUID:
    return uuid.uuid4()
