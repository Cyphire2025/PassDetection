"""
Passport Extraction Service Interface
====================================
Application-facing contract for OCR / MRZ extraction.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PassportExtractionResult:
    extracted_fields: dict[str, Any]
    overall_confidence: float
    confidence_score: dict[str, Any]
    mrz_raw: str | None = None


class IPassportExtractionService(ABC):
    """Contract for passport OCR / MRZ extraction services."""

    @abstractmethod
    async def extract(self, file_content: bytes, *, filename: str, content_type: str) -> PassportExtractionResult:
        """Extract structured passport fields from an uploaded image."""
        ...
