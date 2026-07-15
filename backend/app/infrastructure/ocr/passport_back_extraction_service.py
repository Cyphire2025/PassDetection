"""Lightweight OCR for passport back pages.

Back pages are not ICAO MRZ documents, so this extractor intentionally stores a
separate nested payload instead of pretending the text is authoritative front
page passport data.
"""

from __future__ import annotations

import asyncio
import io
import re
from dataclasses import dataclass

from PIL import Image, ImageOps

from app.core.logging.logger import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class PassportBackExtractionResult:
    fields: dict[str, object]


class PassportBackPageExtractionService:
    async def extract(self, image_bytes: bytes) -> PassportBackExtractionResult:
        text = await asyncio.to_thread(self._ocr_text, image_bytes)
        cleaned_lines = self._clean_lines(text)
        fields: dict[str, object] = {
            "raw_text": "\n".join(cleaned_lines)[:2000],
            "line_count": len(cleaned_lines),
            "source": "passport_back_ocr",
        }
        parsed = self._parse_common_fields(cleaned_lines)
        if parsed:
            fields["parsed"] = parsed
        return PassportBackExtractionResult(fields=fields)

    def _ocr_text(self, image_bytes: bytes) -> str:
        try:
            import pytesseract
        except Exception as exc:
            logger.warning("passport_back_ocr_unavailable", error=str(exc))
            return ""

        try:
            with Image.open(io.BytesIO(image_bytes)) as raw_image:
                image = ImageOps.exif_transpose(raw_image).convert("RGB")
                image.thumbnail((1800, 1800))
                gray = ImageOps.autocontrast(ImageOps.grayscale(image))
                config = "--oem 1 --psm 6 -c preserve_interword_spaces=1"
                return pytesseract.image_to_string(gray, config=config)
        except Exception as exc:
            logger.warning("passport_back_ocr_failed", error=str(exc))
            return ""

    @staticmethod
    def _clean_lines(text: str) -> list[str]:
        lines: list[str] = []
        for line in text.splitlines():
            cleaned = " ".join(line.strip().split())
            if len(cleaned) >= 2:
                lines.append(cleaned)
        return lines[:80]

    def _parse_common_fields(self, lines: list[str]) -> dict[str, str]:
        text = "\n".join(lines)
        parsed: dict[str, str] = {}
        file_match = re.search(r"\b([A-Z]{2}\d{6,}|[A-Z0-9]{10,})\b", text.upper())
        if file_match:
            parsed["possible_file_number"] = file_match.group(1)

        address = self._after_label(lines, ("address", "addr"))
        if address:
            parsed["possible_address"] = address[:500]
        father = self._after_label(lines, ("father", "legal guardian"))
        if father:
            parsed["possible_father_or_guardian_name"] = father[:160]
        mother = self._after_label(lines, ("mother",))
        if mother:
            parsed["possible_mother_name"] = mother[:160]
        spouse = self._after_label(lines, ("spouse", "wife", "husband"))
        if spouse:
            parsed["possible_spouse_name"] = spouse[:160]
        return parsed

    @staticmethod
    def _after_label(lines: list[str], labels: tuple[str, ...]) -> str:
        for index, line in enumerate(lines):
            lowered = line.lower()
            if not any(label in lowered for label in labels):
                continue
            tail = re.split(r"[:\-]", line, maxsplit=1)
            candidates = [tail[1]] if len(tail) == 2 else []
            candidates.extend(lines[index + 1 : index + 4])
            value = " ".join(part.strip() for part in candidates if part.strip())
            return value
        return ""
