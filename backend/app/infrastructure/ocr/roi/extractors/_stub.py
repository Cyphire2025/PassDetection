"""No-op ROI extractor base for future field-specific implementations."""

from __future__ import annotations

from PIL import Image

from app.infrastructure.ocr.roi.base import ROIExtractionResult


class StubROIExtractor:
    field_name = ""

    def extract(self, image: Image.Image) -> ROIExtractionResult | None:
        return None
