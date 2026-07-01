"""EasyOCR adapter."""

from __future__ import annotations

import io
from functools import cached_property
from typing import Any

from PIL import Image, ImageOps

from app.application.interfaces.ocr_engine import IOCREngine, OCRTextResult


class EasyOCREngine(IOCREngine):
    @property
    def name(self) -> str:
        return "easyocr"

    def extract_text(self, image_bytes: bytes) -> OCRTextResult | None:
        with Image.open(io.BytesIO(image_bytes)) as image:
            result = self._reader.readtext(
                self._pil_to_rgb_array(ImageOps.exif_transpose(image)),
                detail=0,
                paragraph=True,
            )

        text = "\n".join(str(item) for item in result if str(item).strip())
        return OCRTextResult(text=text, engine=self.name) if text else None

    @cached_property
    def _reader(self) -> Any:
        import easyocr

        return easyocr.Reader(["en"], gpu=False)

    def _pil_to_rgb_array(self, image: Image.Image) -> Any:
        import numpy as np

        normalized = ImageOps.exif_transpose(image).convert("RGB")
        return np.asarray(normalized)
