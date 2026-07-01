"""
Passport Confidence Scoring Interface
====================================
Application-facing contract for layered extraction confidence scoring.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from app.application.interfaces.passport_field_validator import PassportFieldValidationResult


@dataclass(frozen=True)
class ConfidenceSignal:
    name: str
    score: float
    weight: float
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PassportConfidenceScore:
    overall: float
    level: str
    signals: list[ConfidenceSignal]
    requires_manual_review: bool
    review_reasons: list[str] = field(default_factory=list)
    field_confidence: dict[str, float] = field(default_factory=dict)
    explanation: dict[str, Any] = field(default_factory=dict)
    version: str = "2.0"

    def to_dict(self) -> dict[str, Any]:
        return {
            "overall": self.overall,
            "level": self.level,
            "requires_manual_review": self.requires_manual_review,
            "review_reasons": self.review_reasons,
            "field_confidence": self.field_confidence,
            "explanation": self.explanation,
            "version": self.version,
            "signals": [
                {
                    "name": signal.name,
                    "score": signal.score,
                    "weight": signal.weight,
                    "details": signal.details,
                }
                for signal in self.signals
            ],
        }


class IPassportConfidenceScoringService(ABC):
    """Scores extraction confidence from independent OCR, MRZ, and validation signals."""

    @abstractmethod
    def score(
        self,
        *,
        extracted_fields: dict[str, Any],
        ocr_text: str | None,
        mrz_raw: str | None,
        validation: PassportFieldValidationResult,
        evidence: dict[str, Any] | None = None,
        image_quality: float | None = None,
        fallback_used: bool = False,
    ) -> PassportConfidenceScore:
        """Return a layered confidence score for one extraction result."""
        ...
