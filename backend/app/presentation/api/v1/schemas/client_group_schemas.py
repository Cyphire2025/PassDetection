"""
Upload Link Presentation Schemas
================================
"""

from __future__ import annotations

import uuid
from datetime import datetime
from pydantic import BaseModel, EmailStr, Field


class CreateClientGroupRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)


class ClientGroupResponse(BaseModel):
    id: uuid.UUID
    name: str
    token: str
    agency_id: uuid.UUID
    status: str
    created_by_user_id: uuid.UUID
    created_at: datetime
    closed_at: datetime | None = None

    model_config = {"from_attributes": True}
