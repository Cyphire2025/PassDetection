"""One-pass visual OCR and deterministic passport data-page parsing."""

from __future__ import annotations

import io
import re
import statistics
import time
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Final

from PIL import Image, ImageOps

from app.infrastructure.ocr.mrz import TD3MRZParser

DATA_PAGE_TESSERACT_CONFIG: Final[str] = (
    "--oem 1 --psm 6 --dpi 300 -l eng "
    "-c user_defined_dpi=300 "
    "-c load_system_dawg=0 "
    "-c load_freq_dawg=0 "
    "-c preserve_interword_spaces=1"
)

SUPPORTED_VISUAL_FIELDS: Final[tuple[str, ...]] = (
    "surname",
    "given_names",
    "passport_number",
    "nationality",
    "issuing_country",
    "date_of_birth",
    "date_of_issue",
    "date_of_expiry",
    "sex",
)

_LABEL_PATTERNS: Final[dict[str, re.Pattern[str]]] = {
    "surname": re.compile(r"\bSURNAME\b", re.IGNORECASE),
    "given_names": re.compile(r"\bGIVEN\s+NAMES?\b", re.IGNORECASE),
    "passport_number": re.compile(
        r"\bPASSPORT\s*(?:NO|NUMBER|N[O0]\.?)\b",
        re.IGNORECASE,
    ),
    "nationality": re.compile(r"\bNATIONALITY\b", re.IGNORECASE),
    "issuing_country": re.compile(
        r"\b(?:ISSUING\s+(?:COUNTRY|STATE)|COUNTRY\s+CODE)\b",
        re.IGNORECASE,
    ),
    "date_of_birth": re.compile(r"\b(?:DATE\s+OF\s+BIRTH|DOB)\b", re.IGNORECASE),
    "date_of_issue": re.compile(r"\bDATE\s+OF\s+ISSU[E3]\b", re.IGNORECASE),
    "date_of_expiry": re.compile(
        r"\bDATE\s+OF\s+(?:EXPIRY|EXPIRATION)\b",
        re.IGNORECASE,
    ),
    "sex": re.compile(r"\bSEX\b", re.IGNORECASE),
}

_ISO_DATE = re.compile(r"\b(\d{4})\s*[-/.]\s*(\d{1,2})\s*[-/.]\s*(\d{1,2})\b")
_DAY_FIRST_DATE = re.compile(r"\b(\d{1,2})\s*[-/.]\s*(\d{1,2})\s*[-/.]\s*(\d{4})\b")
_NAMED_DATE = re.compile(
    r"\b(\d{1,2})\s+"
    r"(JAN(?:UARY)?|FEB(?:RUARY)?|MAR(?:CH)?|APR(?:IL)?|MAY|JUN(?:E)?|"
    r"JUL(?:Y)?|AUG(?:UST)?|SEP(?:TEMBER)?|OCT(?:OBER)?|NOV(?:EMBER)?|"
    r"DEC(?:EMBER)?)"
    r"\s+(\d{4})\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class DataPageOCRLine:
    text: str
    confidence: float


@dataclass(frozen=True)
class DataPageOCRResult:
    lines: tuple[DataPageOCRLine, ...]
    text: str
    confidence: float
    duration_ms: float
    debug: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ParsedVisualField:
    field_name: str
    value: str
    confidence: float
    source: str
    debug: dict[str, object] = field(default_factory=dict)


class DataPageOCRReader:
    """Runs one Tesseract read over the normalized passport data page."""

    def read(self, image_bytes: bytes, *, timeout_seconds: float) -> DataPageOCRResult:
        started = time.perf_counter()
        with Image.open(io.BytesIO(image_bytes)) as raw_image:
            image = ImageOps.autocontrast(ImageOps.grayscale(ImageOps.exif_transpose(raw_image)))
            image.thumbnail((1800, 1800), Image.Resampling.LANCZOS)
            image.info["dpi"] = (300, 300)
            prepared_size = image.size
            try:
                import pytesseract
                from pytesseract import Output

                data = pytesseract.image_to_data(
                    image,
                    config=DATA_PAGE_TESSERACT_CONFIG,
                    output_type=Output.DICT,
                    timeout=max(0.1, timeout_seconds),
                )
            finally:
                image.close()

        lines = self._lines(data)
        confidences = [
            line.confidence
            for line in lines
            if line.confidence >= 0
        ]
        return DataPageOCRResult(
            lines=tuple(lines),
            text="\n".join(line.text for line in lines),
            confidence=(
                round(max(0.0, min(1.0, statistics.mean(confidences))), 3)
                if confidences
                else 0.0
            ),
            duration_ms=round((time.perf_counter() - started) * 1000, 2),
            debug={
                "prepared_size": prepared_size,
                "line_count": len(lines),
                "ocr_invocations": 1,
            },
        )

    @classmethod
    def _lines(cls, data: dict[str, list[Any]]) -> list[DataPageOCRLine]:
        grouped: dict[tuple[int, int, int, int], list[tuple[int, str, float]]] = {}
        for index, raw_text in enumerate(data.get("text", [])):
            text = re.sub(r"\s+", " ", str(raw_text)).strip()
            if not text:
                continue
            key = (
                cls._int_at(data, "page_num", index),
                cls._int_at(data, "block_num", index),
                cls._int_at(data, "par_num", index),
                cls._int_at(data, "line_num", index),
            )
            grouped.setdefault(key, []).append(
                (
                    cls._int_at(data, "left", index),
                    text,
                    cls._confidence_at(data, index),
                )
            )

        lines: list[DataPageOCRLine] = []
        for _, tokens in sorted(grouped.items()):
            ordered = sorted(tokens, key=lambda item: item[0])
            confidences = [confidence for _, _, confidence in ordered if confidence >= 0]
            lines.append(
                DataPageOCRLine(
                    text=" ".join(text for _, text, _ in ordered),
                    confidence=(
                        round(statistics.mean(confidences) / 100, 3)
                        if confidences
                        else 0.0
                    ),
                )
            )
        return lines

    @staticmethod
    def _int_at(data: dict[str, list[Any]], key: str, index: int) -> int:
        try:
            return int(data.get(key, [0])[index])
        except (IndexError, TypeError, ValueError):
            return 0

    @staticmethod
    def _confidence_at(data: dict[str, list[Any]], index: int) -> float:
        try:
            return float(data.get("conf", [-1])[index])
        except (IndexError, TypeError, ValueError):
            return -1.0


class PassportDataPageParser:
    """Extracts typed values from one OCR result without invoking OCR again."""

    def __init__(self, *, mrz_parser: TD3MRZParser | None = None) -> None:
        self._mrz_parser = mrz_parser or TD3MRZParser()

    def parse(
        self,
        result: DataPageOCRResult,
        requested_fields: set[str],
    ) -> dict[str, ParsedVisualField]:
        requested = set(SUPPORTED_VISUAL_FIELDS) & requested_fields
        parsed: dict[str, ParsedVisualField] = {}

        # A full-page read can contain the MRZ even when the dedicated crop was
        # poor. Reusing this same OCR text is deterministic parsing, not a
        # second OCR attempt.
        mrz = self._mrz_parser.parse_from_ocr_text(result.text)
        if mrz is not None:
            for field_name in requested:
                value = str(mrz.fields.get(field_name) or "").strip()
                if value:
                    parsed[field_name] = ParsedVisualField(
                        field_name=field_name,
                        value=value,
                        confidence=max(0.7, result.confidence),
                        source="data_page_mrz",
                        debug={"parser": "td3_from_data_page_read"},
                    )

        for field_name in requested - parsed.keys():
            candidate = self._labeled_candidate(field_name, result.lines)
            if candidate is None:
                continue
            value, confidence, offset = candidate
            parsed[field_name] = ParsedVisualField(
                field_name=field_name,
                value=value,
                confidence=confidence,
                source="data_page_label",
                debug={
                    "parser": "label_anchor",
                    "label": field_name,
                    "line_offset": offset,
                },
            )
        return parsed

    def _labeled_candidate(
        self,
        field_name: str,
        lines: tuple[DataPageOCRLine, ...],
    ) -> tuple[str, float, int] | None:
        pattern = _LABEL_PATTERNS[field_name]
        for line_index, line in enumerate(lines):
            match = pattern.search(line.text)
            if match is None or line.confidence < 0.45:
                continue

            candidates: list[tuple[str, float, int]] = []
            same_line = self._truncate_at_other_label(line.text[match.end():])
            if same_line:
                candidates.append((same_line, line.confidence, 0))
            for offset in (1, 2):
                if line_index + offset >= len(lines):
                    break
                next_line = lines[line_index + offset]
                if self._contains_label(next_line.text):
                    break
                candidates.append((next_line.text, next_line.confidence, offset))

            for raw_value, confidence, offset in candidates:
                if confidence < (0.52 if offset == 0 else 0.62):
                    continue
                value = self._parse_value(field_name, raw_value)
                if value:
                    return value, round(min(0.99, confidence), 3), offset
        return None

    @staticmethod
    def _contains_label(text: str) -> bool:
        return any(pattern.search(text) for pattern in _LABEL_PATTERNS.values())

    @staticmethod
    def _truncate_at_other_label(text: str) -> str:
        boundaries = [
            match.start()
            for pattern in _LABEL_PATTERNS.values()
            if (match := pattern.search(text)) is not None
        ]
        return text[:min(boundaries)].strip(" :-") if boundaries else text.strip(" :-")

    def _parse_value(self, field_name: str, raw_value: str) -> str:
        value = re.sub(r"\s+", " ", raw_value).strip()
        if not value or len(value) > 160:
            return ""
        if field_name in {"surname", "given_names"}:
            normalized = re.sub(r"[^A-Z '\-.]", "", value.upper()).strip(" .-")
            return (
                normalized
                if 2 <= len(normalized) <= 100 and any(character.isalpha() for character in normalized)
                else ""
            )
        if field_name == "passport_number":
            compact = re.sub(r"[^A-Z0-9]", "", value.upper())
            strict = re.search(r"[A-Z][0-9]{7}", compact)
            if strict:
                return strict.group(0)
            generic = re.search(r"[A-Z0-9]{6,12}", compact)
            if generic and any(char.isalpha() for char in generic.group(0)) and any(
                char.isdigit() for char in generic.group(0)
            ):
                return generic.group(0)
            return ""
        if field_name in {"nationality", "issuing_country"}:
            return self._country_code(value)
        if field_name in {"date_of_birth", "date_of_issue", "date_of_expiry"}:
            return self._date_value(value, field_name)
        if field_name == "sex":
            normalized = value.upper().strip(" .:-")
            token = re.match(r"(MALE|FEMALE|UNSPECIFIED|M|F|X)\b", normalized)
            if token is None:
                return ""
            return {
                "MALE": "M",
                "FEMALE": "F",
                "UNSPECIFIED": "X",
            }.get(token.group(1), token.group(1))
        return ""

    @staticmethod
    def _country_code(value: str) -> str:
        normalized = re.sub(r"[^A-Z ]", " ", value.upper())
        normalized = re.sub(r"\s+", " ", normalized).strip()
        for candidate in (
            normalized,
            *normalized.split(),
            *[
                " ".join(normalized.split()[index:index + 2])
                for index in range(max(0, len(normalized.split()) - 1))
            ],
        ):
            if re.fullmatch(r"[A-Z]{3}", candidate):
                return candidate
            try:
                import pycountry

                country = pycountry.countries.lookup(candidate)
            except (ImportError, LookupError):
                continue
            return str(country.alpha_3)
        return ""

    @staticmethod
    def _date_value(value: str, field_name: str) -> str:
        normalized = value.upper()
        parsed: date | None = None
        if match := _ISO_DATE.search(normalized):
            parsed = PassportDataPageParser._safe_date(
                int(match.group(1)),
                int(match.group(2)),
                int(match.group(3)),
            )
        elif match := _DAY_FIRST_DATE.search(normalized):
            parsed = PassportDataPageParser._safe_date(
                int(match.group(3)),
                int(match.group(2)),
                int(match.group(1)),
            )
        elif match := _NAMED_DATE.search(normalized):
            try:
                parsed = datetime.strptime(
                    f"{int(match.group(1)):02d} {match.group(2)[:3]} {match.group(3)}",
                    "%d %b %Y",
                ).date()
            except ValueError:
                parsed = None
        if parsed is None or not date(1900, 1, 1) <= parsed <= date(2100, 12, 31):
            return ""
        if field_name in {"date_of_birth", "date_of_issue"} and parsed > date.today():
            return ""
        if field_name == "date_of_birth" and parsed == date.today():
            return ""
        return parsed.isoformat()

    @staticmethod
    def _safe_date(year: int, month: int, day: int) -> date | None:
        try:
            return date(year, month, day)
        except ValueError:
            return None
