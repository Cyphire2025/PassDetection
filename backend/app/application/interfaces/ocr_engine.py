"""
OCR Engine Interface
====================
Application-facing contract for OCR engines.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class OCRTextResult:
    text: str
    engine: str


class IOCREngine(ABC):
    """Contract implemented by concrete OCR engine adapters."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Stable engine identifier used in logs and configuration."""
        ...

    @abstractmethod
    def extract_text(self, image_bytes: bytes) -> OCRTextResult | None:
        """Extract plain text from image bytes."""
        ...
