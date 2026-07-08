"""
Upload Link Presentation Schemas
================================
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from pydantic import BaseModel, EmailStr, Field


class CreateClientGroupRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    destination: str | None = Field(default=None, max_length=255)
    travel_date: date | None = None
    return_date: date | None = None
    package_name: str | None = Field(default=None, max_length=255)
    notes: str | None = Field(default=None, max_length=2000)


class UpdateClientGroupRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    destination: str | None = Field(default=None, max_length=255)
    travel_date: date | None = None
    return_date: date | None = None
    package_name: str | None = Field(default=None, max_length=255)
    notes: str | None = Field(default=None, max_length=2000)


class ClientGroupResponse(BaseModel):
    id: uuid.UUID
    name: str
    token: str
    agency_id: uuid.UUID
    status: str
    created_by_user_id: uuid.UUID | None
    created_at: datetime
    closed_at: datetime | None = None
    destination: str | None = None
    travel_date: date | None = None
    return_date: date | None = None
    package_name: str | None = None
    notes: str | None = None
    deleted_at: datetime | None = None
    deleted_passport_count: int = 0
    deletion_retained_records: bool = False

    model_config = {"from_attributes": True}
