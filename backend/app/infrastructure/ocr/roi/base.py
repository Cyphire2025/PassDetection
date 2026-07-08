"""Base contracts for field-specific ROI OCR extractors."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from PIL import Image


@dataclass(frozen=True)
class ROIExtractionResult:
    field_name: str
    value: str
    confidence: float
    source: str
    debug: dict[str, object] = field(default_factory=dict)


class ROIFieldExtractor(Protocol):
    field_name: str

    def extract(self, image: Image.Image) -> ROIExtractionResult | None:
        """Return a validated field value from its own ROI, or None."""
