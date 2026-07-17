"""Shared ROI OCR utilities."""

from __future__ import annotations

import io
import re
import statistics
import time
from dataclasses import dataclass
from typing import Any

from PIL import Image, ImageOps

from app.core.config.settings import get_settings

ROI_TESSERACT_BASE_CONFIG = (
    "--oem 1 --dpi 300 -l eng "
    "-c user_defined_dpi=300 "
    "-c load_system_dawg=0 "
    "-c load_freq_dawg=0 "
    "-c tessedit_enable_doc_dict=0 "
    "-c classify_enable_learning=0 "
    "-c preserve_interword_spaces=0"
)


@dataclass(frozen=True)
class OCRTextResult:
    text: str
    confidence: float
    duration_ms: float
    debug: dict[str, Any]


class ROIImageTools:
    @staticmethod
    def open_image(image_bytes: bytes) -> Image.Image:
        with Image.open(io.BytesIO(image_bytes)) as image:
            return ImageOps.exif_transpose(image).convert("RGB")

    @staticmethod
    def relative_crop(image: Image.Image, box: tuple[float, float, float, float]) -> Image.Image:
        width, height = image.size
        left = max(0, min(width, round(width * box[0])))
        top = max(0, min(height, round(height * box[1])))
        right = max(left + 1, min(width, round(width * box[2])))
        bottom = max(top + 1, min(height, round(height * box[3])))
        return image.crop((left, top, right, bottom))

    @staticmethod
    def preprocess_text_roi(crop: Image.Image, *, target_height: int = 110) -> Image.Image:
        image = ImageOps.autocontrast(ImageOps.grayscale(crop))
        if image.height > 0 and image.height != target_height:
            scale = target_height / image.height
            image = image.resize((max(1, round(image.width * scale)), target_height), Image.Resampling.LANCZOS)
        image = ImageOps.expand(image, border=(18, 14, 18, 14), fill=255)
        image.info["dpi"] = (300, 300)
        return image

    @staticmethod
    def ocr_single_line(image: Image.Image, *, whitelist: str, psm: int = 7) -> OCRTextResult:
        started = time.perf_counter()
        config = f"{ROI_TESSERACT_BASE_CONFIG} --psm {psm} -c tessedit_char_whitelist={whitelist}"
        try:
            import pytesseract
            from pytesseract import Output

            data = pytesseract.image_to_data(
                image,
                config=config,
                output_type=Output.DICT,
                timeout=get_settings().roi_field_timeout_seconds,
            )
        finally:
            image.close()

        tokens = [
            re.sub(rf"[^{re.escape(whitelist)}]", "", str(token).upper())
            for token in data.get("text", [])
        ]
        text = " ".join(token for token in tokens if token)
        confidences = [
            float(value)
            for value in data.get("conf", [])
            if ROIImageTools._is_confidence(value)
        ]
        confidence = round(max(0.0, min(1.0, statistics.mean(confidences) / 100)), 3) if confidences else 0.0
        return OCRTextResult(
            text=text,
            confidence=confidence,
            duration_ms=round((time.perf_counter() - started) * 1000, 2),
            debug={"config": config, "raw_tokens": tokens},
        )

    @staticmethod
    def _is_confidence(value: object) -> bool:
        try:
            return float(str(value)) >= 0
        except (TypeError, ValueError):
            return False
