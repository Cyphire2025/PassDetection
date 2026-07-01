"""
MRZ Parser Interface
====================
Application-facing contract for machine-readable zone parsing.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass(frozen=True)
class MRZParseResult:
    fields: dict[str, str]
    raw_text: str
    warnings: list[str] = field(default_factory=list)


class IMRZParser(ABC):
    """Contract for MRZ parsers."""

    @abstractmethod
    def parse(self, raw_text: str | None) -> MRZParseResult | None:
        """Parse raw MRZ text into structured passport fields."""
        ...

    @abstractmethod
    def parse_from_ocr_text(self, text: str) -> MRZParseResult | None:
        """Recover and parse MRZ lines from noisy OCR text."""
        ...
