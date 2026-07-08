"""Factory for pluggable MRZ OCR engines."""

from __future__ import annotations

from functools import lru_cache

from app.core.config.settings import MRZSettings
from app.infrastructure.ocr.mrz_ocr import ICAOTD3MRZOCR
from app.infrastructure.ocr.mrz_ocr_base import MRZOCRReader


@lru_cache(maxsize=1)
def _tesseract_reader() -> ICAOTD3MRZOCR:
    return ICAOTD3MRZOCR()


def build_mrz_ocr_reader(settings: MRZSettings) -> MRZOCRReader:
    _ = settings
    return _tesseract_reader()
