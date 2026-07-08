"""
Global Search Schemas
=====================
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel


class GlobalSearchResult(BaseModel):
    type: str
    id: uuid.UUID
    group_id: uuid.UUID | None = None
    title: str
    subtitle: str | None = None
    status: str | None = None
    passport_number: str | None = None
    client_name: str | None = None
    client_email: str | None = None
    client_phone: str | None = None
    group_name: str | None = None
    destination: str | None = None
    updated_at: datetime | None = None
