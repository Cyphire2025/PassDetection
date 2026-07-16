"""
Dashboard Presentation Schemas (Pydantic)
=========================================
Request/response schemas for the dashboard API.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel


class RecentSubmissionResponse(BaseModel):
    id: uuid.UUID
    client_name: str
    client_email: str | None = None
    status: str
    created_at: datetime
    overall_confidence: float | None

    model_config = {"from_attributes": True}


class DashboardStatsResponse(BaseModel):
    total_passports: int
    pending_review: int
    confirmed: int
    active_links: int
    recent_submissions: list[RecentSubmissionResponse]

    model_config = {"from_attributes": True}
