"""Application boundary for AI-assisted travel email analysis."""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.domain.value_objects.email_ai_analysis import (
    EmailAnalysisRequest,
    EmailAnalysisResult,
)


class IEmailAnalysisService(ABC):
    """Analyze one bounded email and return a conservative typed result."""

    @abstractmethod
    async def analyze(self, request: EmailAnalysisRequest) -> EmailAnalysisResult:
        """Return a review-safe result; provider failures must not escape."""
        ...
