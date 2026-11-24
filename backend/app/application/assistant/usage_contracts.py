"""Private usage read model for the super administrator."""

from datetime import datetime

from pydantic import BaseModel

from app.core.assistant_usage import AssistantUsageLimits


class AssistantUsageResponse(BaseModel):
    observed_at: datetime
    resets_at: datetime
    limits: AssistantUsageLimits
    used: dict[str, int]
