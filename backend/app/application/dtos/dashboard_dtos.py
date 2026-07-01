"""
Dashboard Application DTOs
==========================
Data Transfer Objects for dashboard stats and activity feeds.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class RecentSubmissionDTO:
    """Represents a simplified submission for activity lists."""
    id: uuid.UUID
    client_name: str
    client_email: str | None
    status: str
    created_at: datetime
    overall_confidence: float | None


@dataclass(frozen=True)
class DashboardStatsDTO:
    """Aggregate statistics for an agency's dashboard."""
    total_passports: int
    pending_review: int
    confirmed: int
    active_links: int
    recent_submissions: list[RecentSubmissionDTO]
