"""Extraction-first global Gemini scheduling."""

from app.infrastructure.ai_priority.config import (
    PREPARED_SETTING_NAMES,
    AiPriorityConfig,
)
from app.infrastructure.ai_priority.coordinator import AiPriorityCoordinator
from app.infrastructure.ai_priority.factory import get_ai_priority_coordinator
from app.infrastructure.ai_priority.runtime import (
    AiPriorityAdmissionDeferred,
    MaintainPriorityLease,
)
from app.infrastructure.ai_priority.state import (
    AdmissionDecision,
    AdmissionStatus,
    AiWorkload,
    PriorityLease,
    QueueCounts,
)

EXTRACTION_QUEUE = "interactive-passport-extraction"
VERIFICATION_QUEUE = "post-submission-ai-verification"

__all__ = [
    "EXTRACTION_QUEUE",
    "PREPARED_SETTING_NAMES",
    "VERIFICATION_QUEUE",
    "AdmissionDecision",
    "AdmissionStatus",
    "AiPriorityAdmissionDeferred",
    "AiPriorityConfig",
    "AiPriorityCoordinator",
    "AiWorkload",
    "MaintainPriorityLease",
    "PriorityLease",
    "QueueCounts",
    "get_ai_priority_coordinator",
]
