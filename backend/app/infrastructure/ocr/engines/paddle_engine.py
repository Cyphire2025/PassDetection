"""PaddleOCR adapter."""

from __future__ import annotations

import io
from functools import cached_property
from typing import Any

from PIL import Image, ImageOps

from app.application.interfaces.ocr_engine import IOCREngine, OCRTextResult


class PaddleOCREngine(IOCREngine):
    @property
    def name(self) -> str:
        return "paddleocr"

    def extract_text(self, image_bytes: bytes) -> OCRTextResult | None:
        with Image.open(io.BytesIO(image_bytes)) as image:
            result = self._reader.ocr(self._pil_to_rgb_array(image), cls=True)

        lines: list[str] = []
        for page in result or []:
            for line in page or []:
                if len(line) >= 2 and line[1]:
                    text = str(line[1][0]).strip()
                    if text:
                        lines.append(text)

        extracted = "\n".join(lines)
        return OCRTextResult(text=extracted, engine=self.name) if extracted else None

    @cached_property
    def _reader(self) -> Any:
        from paddleocr import PaddleOCR

        return PaddleOCR(use_angle_cls=True, lang="en", show_log=False)

    def _pil_to_rgb_array(self, image: Image.Image) -> Any:
        import numpy as np

        normalized = ImageOps.exif_transpose(image).convert("RGB")
        return np.asarray(normalized)
