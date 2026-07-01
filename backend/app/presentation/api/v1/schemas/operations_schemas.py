"""
Operational API Schemas
=======================
Schemas for admin, audit, analytics, and notification endpoints.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel
from pydantic import EmailStr, Field


class AuditLogResponse(BaseModel):
    id: uuid.UUID
    agency_id: uuid.UUID | None = None
    user_id: uuid.UUID | None = None
    actor_email: str | None = None
    action: str
    entity_type: str
    entity_id: str | None = None
    ip_address: str | None = None
    metadata: dict[str, Any] | None = None
    created_at: datetime


class NotificationResponse(BaseModel):
    id: uuid.UUID
    agency_id: uuid.UUID
    user_id: uuid.UUID | None = None
    type: str
    title: str
    message: str
    entity_type: str | None = None
    entity_id: str | None = None
    is_read: bool
    created_at: datetime
    read_at: datetime | None = None


class AdminOverviewResponse(BaseModel):
    agencies: int
    users: int
    client_groups: int
    passport_submissions: int
    pending_review: int
    client_submitted: int
    failed: int


class CreateManagerRequest(BaseModel):
    full_name: str = Field(..., min_length=2, max_length=255)
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)


class ManagerResponse(BaseModel):
    id: uuid.UUID
    full_name: str
    email: EmailStr
    role: str
    agency_id: uuid.UUID | None
    is_active: bool
    created_at: datetime
    last_login_at: datetime | None = None


class AnalyticsSummaryResponse(BaseModel):
    status_counts: dict[str, int]
    confidence_buckets: dict[str, int]
    submissions_by_day: dict[str, int]
    average_confidence: float | None
