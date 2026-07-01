"""
Upload Link Application DTOs
=============================
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class CreateClientGroupInputDTO:
    name: str


@dataclass(frozen=True)
class ClientGroupOutputDTO:
    id: uuid.UUID
    name: str
    token: str
    agency_id: uuid.UUID
    status: str
    created_by_user_id: uuid.UUID
    created_at: datetime
    closed_at: datetime | None = None
