"""Factory for pluggable MRZ OCR engines."""

from __future__ import annotations

from functools import lru_cache

from app.core.config.settings import MRZSettings
from app.infrastructure.ocr.mrz_ocr import ICAOTD3MRZOCR
from app.infrastructure.ocr.mrz_ocr_base import MRZOCRReader


@lru_cache(maxsize=4)
def _tesseract_reader(timeout_seconds: float) -> ICAOTD3MRZOCR:
    return ICAOTD3MRZOCR(timeout_seconds=timeout_seconds)


def build_mrz_ocr_reader(settings: MRZSettings) -> MRZOCRReader:
    return _tesseract_reader(settings.timeout_seconds)
