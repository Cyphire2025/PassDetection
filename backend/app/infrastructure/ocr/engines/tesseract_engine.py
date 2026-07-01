"""Tesseract OCR adapter."""

from __future__ import annotations

import io

from PIL import Image, ImageOps

from app.application.interfaces.ocr_engine import IOCREngine, OCRTextResult


class TesseractOCREngine(IOCREngine):
    @property
    def name(self) -> str:
        return "tesseract"

    def extract_text(self, image_bytes: bytes) -> OCRTextResult | None:
        import pytesseract

        with Image.open(io.BytesIO(image_bytes)) as image:
            prepared = ImageOps.grayscale(ImageOps.autocontrast(image))
            text = pytesseract.image_to_string(prepared)

        return OCRTextResult(text=text, engine=self.name) if text else None
