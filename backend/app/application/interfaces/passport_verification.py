"""Application contract for best-effort AI passport verification."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PassportVerificationResult:
    """Merged review fields plus non-sensitive verification diagnostics."""

    merged_fields: dict[str, Any]
    metadata: dict[str, Any]


class IPassportVerificationService(ABC):
    """Classifies the submitted image and verifies OCR fields against it."""

    @abstractmethod
    async def verify(
        self,
        image_content: bytes,
        *,
        content_type: str,
        extracted_fields: dict[str, Any],
        timeout_seconds: float | None = None,
    ) -> PassportVerificationResult:
        """Return conservatively merged fields plus a conclusive classification status."""
        ...
