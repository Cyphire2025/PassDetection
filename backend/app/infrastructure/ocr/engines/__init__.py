"""OCR engine adapters and compatibility factory."""

from app.infrastructure.ocr.engines.easyocr_engine import EasyOCREngine
from app.infrastructure.ocr.engines.factory import OCREngineFactory, build_ocr_engine
from app.infrastructure.ocr.engines.paddle_engine import PaddleOCREngine
from app.infrastructure.ocr.engines.tesseract_engine import TesseractOCREngine

__all__ = [
    "EasyOCREngine",
    "OCREngineFactory",
    "PaddleOCREngine",
    "TesseractOCREngine",
    "build_ocr_engine",
]
