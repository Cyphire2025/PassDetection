"""Single-pass ICAO TD3 MRZ OCR."""

from __future__ import annotations

import statistics
import time
from dataclasses import dataclass, field
from typing import Any

from PIL import Image, ImageOps

from app.infrastructure.ocr.mrz_image_normalizer import MRZImageNormalizer


MRZ_TESSERACT_CONFIG = (
    "--oem 1 --psm 6 --dpi 300 -l eng "
    "-c user_defined_dpi=300 "
    "-c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789< "
    "-c load_system_dawg=0 "
    "-c load_freq_dawg=0 "
    "-c tessedit_enable_doc_dict=0 "
    "-c classify_enable_learning=0 "
    "-c preserve_interword_spaces=0"
)


@dataclass(frozen=True)
class MRZOCRResult:
    text: str
    confidence: float
    duration_ms: float
    debug: dict[str, Any] = field(default_factory=dict)


class ICAOTD3MRZOCR:
    """Prepares a detected TD3 MRZ crop and reads it with one Tesseract pass."""

    engine_name = "tesseract"

    def __init__(self, *, normalizer: MRZImageNormalizer | None = None) -> None:
        self._normalizer = normalizer or MRZImageNormalizer()

    def read(self, crop: Image.Image, *, normalize: bool = False) -> MRZOCRResult:
        started = time.perf_counter()
        prepared = self.prepare(crop, normalize=normalize)
        try:
            import pytesseract
            from pytesseract import Output

            data = pytesseract.image_to_data(
                prepared,
                config=MRZ_TESSERACT_CONFIG,
                output_type=Output.DICT,
            )
        finally:
            prepared.close()

        lines = self._extract_lines(data)
        text = "\n".join(lines)
        confidences = [
            float(value)
            for value in data.get("conf", [])
            if self._is_confidence(value)
        ]
        confidence = round(max(0.0, min(1.0, statistics.mean(confidences) / 100)), 3) if confidences else 0.0
        return MRZOCRResult(
            text=text,
            confidence=confidence,
            duration_ms=round((time.perf_counter() - started) * 1000, 2),
            debug={
                "config": MRZ_TESSERACT_CONFIG,
                "input_size": crop.size,
                "normalizer_used": normalize,
                "prepared_size": prepared.size,
                "word_count": len([line for line in lines if line]),
            },
        )

    def prepare(self, crop: Image.Image, *, normalize: bool = False) -> Image.Image:
        if normalize:
            return self._normalizer.normalize(crop)
        return self._standard_prepare(crop)

    @staticmethod
    def _standard_prepare(crop: Image.Image) -> Image.Image:
        image = ImageOps.autocontrast(ImageOps.grayscale(crop))
        target_height = 240
        if image.height > 0 and image.height != target_height:
            scale = target_height / image.height
            image = image.resize(
                (max(1, round(image.width * scale)), target_height),
                Image.Resampling.LANCZOS,
            )
        image.info["dpi"] = (300, 300)
        return image

    @staticmethod
    def _extract_lines(data: dict[str, list[Any]]) -> list[str]:
        grouped: dict[tuple[int, int, int], list[tuple[int, str]]] = {}
        for index, raw_text in enumerate(data.get("text", [])):
            text = "".join(char for char in str(raw_text).upper() if char.isalnum() or char == "<")
            if not text:
                continue
            key = (
                int(data["block_num"][index]),
                int(data["par_num"][index]),
                int(data["line_num"][index]),
            )
            grouped.setdefault(key, []).append((int(data["left"][index]), text))

        lines = [
            "".join(text for _, text in sorted(parts, key=lambda item: item[0]))
            for _, parts in sorted(grouped.items(), key=lambda item: item[0])
        ]
        return [line for line in lines if line]

    @staticmethod
    def _is_confidence(value: Any) -> bool:
        try:
            return float(value) >= 0
        except (TypeError, ValueError):
            return False
