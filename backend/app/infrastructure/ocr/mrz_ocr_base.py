"""Common interface for MRZ OCR engines."""

from __future__ import annotations

from typing import Protocol

from PIL import Image

from app.infrastructure.ocr.mrz_ocr import MRZOCRResult


class MRZOCRReader(Protocol):
    """Reads text from a detected MRZ crop."""

    engine_name: str

    def read(self, crop: Image.Image, *, normalize: bool = False) -> MRZOCRResult:
        """Return raw MRZ OCR text and confidence for the supplied crop."""
