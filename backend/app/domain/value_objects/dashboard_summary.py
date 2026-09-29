"""Small dashboard projections, independent of document/source payloads."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.domain.entities.entities import PassportProcessingStatus

RECENT_DASHBOARD_LIMIT = 5
RECENT_DASHBOARD_TEXT_LIMIT = 255


class DashboardProjectionLimitError(ValueError):
    """A complete authorized preview cannot fit its fixed field bounds."""


@dataclass(frozen=True)
class DashboardRecentSubmission:
    id: UUID
    client_name: str
    client_email: str | None
    status: PassportProcessingStatus
    created_at: datetime
    overall_confidence: float | None
