"""Minimal Stage 1 passport extraction components."""

from __future__ import annotations

import asyncio
import io
import re
import time
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from PIL import Image, ImageFilter, ImageOps

from app.core.logging.logger import get_logger
from app.infrastructure.ocr.mrz import TD3MRZParser
from app.infrastructure.ocr.preprocessing import OCRImagePreprocessor

logger = get_logger(__name__)


CORE_FIELDS = (
    "surname",
    "given_names",
    "passport_number",
    "nationality",
    "issuing_country",
    "date_of_birth",
    "date_of_expiry",
    "sex",
)

UNCHECKSUMMED_MRZ_FIELDS = {"surname", "given_names"}


@dataclass(frozen=True)
class StageTiming:
    name: str
    duration_ms: float
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "duration_ms": self.duration_ms, **self.metadata}


@dataclass(frozen=True)
class MRZStageResult:
    fields: dict[str, str]
    raw_text: str | None
    ocr_text: str | None
    warnings: list[str]
    duration_ms: float


@dataclass(frozen=True)
class TargetedOCRResult:
    fields: dict[str, str]
    raw_text: dict[str, str]
    duration_ms: float


class Stage1MRZExtractor:
    """Reads the TD3 MRZ strip once and parses it with checksum validation."""

    def __init__(
        self,
        *,
        preprocessor: OCRImagePreprocessor,
        parser: TD3MRZParser,
        timeout_seconds: float,
    ) -> None:
        self._preprocessor = preprocessor
        self._parser = parser
        self._timeout_seconds = timeout_seconds

    async def extract(self, image_bytes: bytes) -> MRZStageResult:
        started = time.perf_counter()
        text = await self._read_mrz_text(image_bytes)
        sanitized_text = self._sanitize_indian_td3_text(text)
        parsed = self._parser.parse(sanitized_text) if sanitized_text else None
        if parsed is None and sanitized_text:
            parsed = self._parser.parse_from_ocr_text(sanitized_text)
        if parsed is None:
            parsed = self._parser.parse_from_ocr_text(text) if text else None
        if parsed is None:
            parsed = self._parser.parse(text)
        fields = dict(parsed.fields) if parsed else {}
        partial_names = self._extract_partial_names(text)
        for field_name, value in partial_names.items():
            fields.setdefault(field_name, value)
        warnings = list(parsed.warnings) if parsed else []
        if partial_names and not parsed:
            warnings.append("MRZ names could not be checksum-validated and require visual verification.")
        return MRZStageResult(
            fields=fields,
            raw_text=parsed.raw_text if parsed else sanitized_text,
            ocr_text=text or None,
            warnings=warnings,
            duration_ms=_elapsed_ms(started),
        )

    async def _read_mrz_text(self, image_bytes: bytes) -> str:
        try:
            import pytesseract  # noqa: F401
        except Exception as exc:
            logger.warning("stage1_mrz_tesseract_unavailable", error=str(exc))
            return ""

        image, config = await asyncio.to_thread(self._prepare_mrz_crop, image_bytes)
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(self._image_to_string, image, config),
                timeout=self._timeout_seconds,
            )
        except TimeoutError:
            logger.warning("stage1_mrz_ocr_timeout", timeout_seconds=self._timeout_seconds)
            return ""
        except Exception as exc:
            logger.warning("stage1_mrz_ocr_failed", error=str(exc))
            return ""
        finally:
            image.close()

    def _prepare_mrz_crop(self, image_bytes: bytes):  # type: ignore[no-untyped-def]
        with Image.open(io.BytesIO(image_bytes)) as raw_image:
            base = ImageOps.exif_transpose(raw_image).convert("RGB")
            base.thumbnail((1800, 1800))
            gray = ImageOps.autocontrast(ImageOps.grayscale(base))
            width, height = gray.size
            crop = gray.crop((0, int(height * 0.55), width, height))
            prepared = self._preprocessor.upscale(crop, 2)
        config = "--oem 1 --psm 6"
        return prepared, config

    @staticmethod
    def _image_to_string(image, config: str) -> str:  # type: ignore[no-untyped-def]
        import pytesseract

        return pytesseract.image_to_string(image, config=config).strip().upper()

    def _sanitize_indian_td3_text(self, text: str) -> str | None:
        tokens = re.findall(r"[A-Z0-9<]{20,}", (text or "").upper().replace(" ", ""))
        if len(tokens) < 2:
            return None

        line1 = next((token for token in tokens if token.startswith("P<")), None)
        line2 = next((token for token in tokens if not token.startswith("P<") and len(token) >= 40), None)
        if not line1 or not line2:
            return None

        normalized_line1 = self._normalize_indian_line1(line1)
        if not normalized_line1:
            return None
        return f"{normalized_line1}\n{line2[:44]}"

    def _extract_partial_names(self, text: str) -> dict[str, str]:
        for raw_line in (text or "").upper().splitlines():
            line = re.sub(r"[^A-Z0-9<]", "", raw_line)
            start = line.find("P<")
            if start < 0:
                continue
            line = line[start:]
            if len(line) < 12:
                continue
            country = "".join(self._normalize_alpha(char) for char in line[2:5])
            if self._edit_distance(country, "IND") > 1:
                continue

            names = line[5:]
            if "<<" in names:
                surname_raw, given_raw = names.split("<<", 1)
            else:
                separator = names.find("<")
                if separator < 2:
                    continue
                surname_raw = names[:separator]
                if surname_raw.endswith(("C", "K")):
                    surname_raw = surname_raw[:-1]
                given_raw = names[separator + 1:]

            surname = re.sub(r"[^A-Z]", "", surname_raw)
            given_match = re.match(r"([A-Z]+?)(?:[<K5S]{3,}|$)", given_raw)
            given_names = given_match.group(1) if given_match else ""
            return {
                key: value
                for key, value in {"surname": surname, "given_names": given_names}.items()
                if len(value) >= 2
            }
        return {}

    @staticmethod
    def _normalize_alpha(char: str) -> str:
        return {"0": "O", "1": "I", "2": "Z", "5": "S", "6": "G", "8": "B", "L": "I"}.get(char, char)

    def _normalize_indian_line1(self, token: str) -> str | None:
        normalized = re.sub(r"[^A-Z0-9<]", "", token.upper())
        if not normalized.startswith("P<"):
            return None

        country_and_names = normalized[2:]
        payload: str | None = None
        if country_and_names.startswith("IND"):
            payload = country_and_names[3:]
        elif len(country_and_names) >= 4:
            prefix4 = country_and_names[:4]
            for index in range(4):
                if prefix4[:index] + prefix4[index + 1:] == "IND":
                    payload = country_and_names[4:]
                    break
        if payload is None and self._edit_distance(country_and_names[:3], "IND") <= 1:
            payload = country_and_names[3:]
        if payload is None:
            return None

        payload = re.sub(r"[^A-Z<]", "", payload)
        if "<<" not in payload:
            return None
        return f"P<IND{payload}"[:44].ljust(44, "<")

    @staticmethod
    def _edit_distance(left: str, right: str) -> int:
        if len(left) != len(right):
            return max(len(left), len(right))
        return sum(1 for current, expected in zip(left, right) if current != expected)


class Stage1TargetedOCR:
    """Runs fixed-field OCR only for fields not provided by valid MRZ output."""

    _ROIS = {
        "passport_number": (0.72, 0.08, 0.99, 0.19),
        "nationality": (0.50, 0.05, 0.76, 0.19),
        "surname": (0.32, 0.16, 0.70, 0.30),
        "given_names": (0.34, 0.32, 0.56, 0.40),
        "date_of_birth": (0.32, 0.35, 0.55, 0.51),
        "sex": (0.55, 0.34, 0.68, 0.51),
        "date_of_expiry": (0.69, 0.60, 0.99, 0.80),
        "issuing_country": (0.33, 0.05, 0.51, 0.19),
    }

    def __init__(self, *, preprocessor: OCRImagePreprocessor, timeout_seconds: float) -> None:
        self._preprocessor = preprocessor
        self._timeout_seconds = timeout_seconds

    async def extract(self, image_bytes: bytes, target_fields: set[str]) -> TargetedOCRResult:
        started = time.perf_counter()
        if not target_fields:
            return TargetedOCRResult(fields={}, raw_text={}, duration_ms=0.0)
        try:
            import pytesseract  # noqa: F401
        except Exception as exc:
            logger.warning("stage1_targeted_tesseract_unavailable", error=str(exc))
            return TargetedOCRResult(fields={}, raw_text={}, duration_ms=_elapsed_ms(started))

        fields: dict[str, str] = {}
        raw_text: dict[str, str] = {}
        with Image.open(io.BytesIO(image_bytes)) as raw_image:
            base = ImageOps.exif_transpose(raw_image).convert("RGB")
            base.thumbnail((1800, 1800))
            for field_name in sorted(target_fields):
                roi = self._ROIS.get(field_name)
                if roi is None:
                    continue
                crop = self._crop(base, roi)
                text = await self._read_field(field_name, crop)
                raw_text[field_name] = text
                value = self._parse_field(field_name, text)
                if value:
                    fields[field_name] = value
        return TargetedOCRResult(fields=fields, raw_text=raw_text, duration_ms=_elapsed_ms(started))

    async def _read_field(self, field_name: str, crop: Image.Image) -> str:
        config = self._tesseract_config(field_name)
        prepared = ImageOps.autocontrast(ImageOps.grayscale(crop))
        prepared = self._preprocessor.upscale(prepared, 4)
        if field_name == "passport_number":
            prepared = prepared.filter(ImageFilter.SHARPEN)
        elif field_name == "given_names":
            prepared = prepared.point(lambda value: 255 if value > 130 else 0)
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(self._image_to_string, prepared, config),
                timeout=self._timeout_seconds,
            )
        except TimeoutError:
            logger.warning("stage1_targeted_ocr_timeout", field=field_name, timeout_seconds=self._timeout_seconds)
            return ""
        except Exception as exc:
            logger.warning("stage1_targeted_ocr_failed", field=field_name, error=str(exc))
            return ""
        finally:
            prepared.close()
            crop.close()

    def _crop(self, image: Image.Image, roi: tuple[float, float, float, float]) -> Image.Image:
        width, height = image.size
        left, top, right, bottom = roi
        return image.crop(
            (
                int(width * left),
                int(height * top),
                int(width * right),
                int(height * bottom),
            )
        )

    @staticmethod
    def _image_to_string(image: Image.Image, config: str) -> str:
        import pytesseract

        return pytesseract.image_to_string(image, config=config).strip().upper()

    @staticmethod
    def _tesseract_config(field_name: str) -> str:
        if field_name in {"date_of_birth", "date_of_expiry"}:
            whitelist = "0123456789/-."
        elif field_name == "sex":
            whitelist = "MFX"
        elif field_name in {"nationality", "issuing_country", "surname", "given_names"}:
            whitelist = "ABCDEFGHIJKLMNOPQRSTUVWXYZ "
        else:
            whitelist = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
        page_mode = 11 if field_name == "surname" else 7 if field_name == "given_names" else 6
        return f"--oem 1 --psm {page_mode} -c tessedit_char_whitelist={whitelist}"

    def _parse_field(self, field_name: str, text: str) -> str | None:
        normalized = re.sub(r"\s+", " ", text.upper()).strip()
        if not normalized:
            return None
        if field_name == "passport_number":
            match = re.search(r"[A-Z][0-9][A-Z0-9]{6,7}", normalized.replace(" ", ""))
            return match.group(0) if match else None
        if field_name in {"nationality", "issuing_country"}:
            letters = re.sub(r"[^A-Z]", "", normalized)
            if any(marker in letters for marker in ("INDIAN", "INDIA", "IND")):
                return "IND"
            return letters[:3] if len(letters) >= 3 else None
        if field_name in {"surname", "given_names"}:
            candidates = [
                re.sub(r"[^A-Z]", "", line)
                for line in text.upper().splitlines()
            ]
            candidates = [
                value for value in candidates
                if len(value) >= 2 and not any(label in value for label in ("SURNAME", "GIVEN", "DATE", "BIRTH", "SEX"))
            ]
            return max(candidates, key=len) if candidates else None
        if field_name in {"date_of_birth", "date_of_expiry"}:
            return self._parse_date(normalized, is_expiry=field_name == "date_of_expiry")
        if field_name == "sex":
            match = re.search(r"\b[MFX]\b|[MFX]", normalized)
            return match.group(0)[0] if match else None
        return normalized

    def _parse_date(self, text: str, *, is_expiry: bool) -> str | None:
        for match in re.finditer(r"([0-3]?\d)[/\-.]([01]?\d)[/\-.]((?:19|20)?\d{2})", text):
            day = int(match.group(1))
            month = int(match.group(2))
            year = int(match.group(3))
            if year < 100:
                year += 2000 if is_expiry or year <= 30 else 1900
            try:
                return date(year, month, day).isoformat()
            except ValueError:
                continue
        return None


def invalid_or_missing_fields(fields: dict[str, str], validation_issues: list[Any]) -> set[str]:
    targets = {field for field in CORE_FIELDS if not fields.get(field)}
    targets.update(
        issue.field
        for issue in validation_issues
        if getattr(issue, "field", None) in CORE_FIELDS
    )
    targets.update(UNCHECKSUMMED_MRZ_FIELDS.intersection(fields))
    return targets


def _elapsed_ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 2)
