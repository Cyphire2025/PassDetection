"""Availability-aware OCR engine construction."""

from __future__ import annotations

import importlib.util
from collections.abc import Callable

from app.application.interfaces.ocr_engine import IOCREngine
from app.infrastructure.ocr.engines.easyocr_engine import EasyOCREngine
from app.infrastructure.ocr.engines.paddle_engine import PaddleOCREngine
from app.infrastructure.ocr.engines.tesseract_engine import TesseractOCREngine


class OCREngineFactory:
    """Builds configured OCR adapters without importing unavailable runtimes."""

    _DEPENDENCIES = {
        "paddleocr": "paddle",
        "easyocr": "easyocr",
        "tesseract": "pytesseract",
    }

    def __init__(self, builders: dict[str, Callable[[], IOCREngine]] | None = None) -> None:
        self._builders = builders or {
            "tesseract": TesseractOCREngine,
            "easyocr": EasyOCREngine,
            "paddleocr": PaddleOCREngine,
        }

    def build(self, name: str) -> IOCREngine | None:
        dependency = self._DEPENDENCIES.get(name)
        builder = self._builders.get(name)
        if builder is None or dependency is None:
            return None
        if importlib.util.find_spec(dependency) is None:
            return None
        return builder()


_default_factory = OCREngineFactory()


def build_ocr_engine(name: str) -> IOCREngine | None:
    """Backward-compatible factory retained for existing callers."""

    return _default_factory.build(name)
