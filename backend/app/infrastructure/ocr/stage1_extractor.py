"""Minimal MRZ extraction components."""

from __future__ import annotations

import asyncio
import io
import time
from dataclasses import dataclass, field
from typing import Any

import re

from PIL import Image, ImageOps

from app.core.logging.logger import get_logger
from app.infrastructure.ocr.correction import ICAOCorrectionEngine
from app.infrastructure.ocr.detection import MRZRegionDetector
from app.infrastructure.ocr.mrz import TD3MRZParser
from app.infrastructure.ocr.mrz_ocr import MRZOCRResult
from app.infrastructure.ocr.mrz_ocr_base import MRZOCRReader
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
    ocr_confidence: float = 0.0
    correction_provenance: dict[str, dict[str, str | float]] = field(default_factory=dict)
    corrected_mrz_text: str | None = None
    correction_duration_ms: float = 0.0
    checksum_pass_rate: float = 0.0
    ocr_attempts: list[dict[str, Any]] = field(default_factory=list)


class Stage1MRZExtractor:
    """Reads the TD3 MRZ strip once and parses it with checksum validation."""

    def __init__(
        self,
        *,
        preprocessor: OCRImagePreprocessor,
        parser: TD3MRZParser,
        timeout_seconds: float,
        detector: MRZRegionDetector | None = None,
        ocr_reader: MRZOCRReader | None = None,
        correction_engine: ICAOCorrectionEngine | None = None,
    ) -> None:
        self._preprocessor = preprocessor
        self._parser = parser
        self._timeout_seconds = timeout_seconds
        self._detector = detector or MRZRegionDetector()
        if ocr_reader is None:
            from app.core.config.settings import get_settings
            from app.infrastructure.ocr.mrz_ocr_factory import build_mrz_ocr_reader

            ocr_reader = build_mrz_ocr_reader(get_settings().mrz)
        self._ocr_reader = ocr_reader
        self._correction_engine = correction_engine or ICAOCorrectionEngine()

    async def extract(self, image_bytes: bytes) -> MRZStageResult:
        started = time.perf_counter()
        image = await asyncio.to_thread(self._prepare_mrz_crop, image_bytes)
        try:
            primary_ocr = await self._read_mrz_text(image, normalize=False)
            primary = self._build_result(primary_ocr, started=started)
            invalid_fields = self._invalid_required_fields(primary)
            if not invalid_fields:
                return primary

            fallback_ocr = await self._read_mrz_text(image, normalize=True)
            fallback = self._build_result(fallback_ocr, started=started)
            return self._merge_fallback_result(
                primary=primary,
                fallback=fallback,
                invalid_fields=invalid_fields,
                duration_ms=_elapsed_ms(started),
            )
        finally:
            image.close()

    def _build_result(self, ocr_result: MRZOCRResult, *, started: float) -> MRZStageResult:
        text = ocr_result.text
        correction = self._correction_engine.correct(text)
        corrected_text = correction.corrected_mrz
        parsed = self._parser.parse(corrected_text) if corrected_text else None
        sanitized_text = None if parsed else self._sanitize_indian_td3_text(text)
        if parsed is None and sanitized_text:
            parsed = self._parser.parse_from_ocr_text(sanitized_text)
        if parsed is None:
            parsed = self._parser.parse_from_ocr_text(text) if text else None
        if parsed is None:
            parsed = self._parser.parse(text)
        fields = dict(parsed.fields) if parsed else {}
        self._remove_unproven_fields(fields, correction.provenance_dict())
        partial_names = self._extract_partial_names(text) or self._extract_partial_names(corrected_text or "")
        for field_name, value in partial_names.items():
            if self._field_is_proven(field_name, correction.provenance_dict()):
                current = fields.get(field_name)
                if not current or self._should_replace_partial_name(current, value):
                    fields[field_name] = value
        warnings = [*correction.warnings, *(parsed.warnings if parsed else [])]
        if partial_names and not parsed:
            warnings.append("MRZ names could not be checksum-validated and require visual verification.")
        return MRZStageResult(
            fields=fields,
            raw_text=parsed.raw_text if parsed else corrected_text or sanitized_text,
            ocr_text=text or None,
            warnings=warnings,
            duration_ms=_elapsed_ms(started),
            ocr_confidence=ocr_result.confidence,
            correction_provenance=correction.provenance_dict(),
            corrected_mrz_text=corrected_text,
            correction_duration_ms=correction.duration_ms,
            checksum_pass_rate=correction.checksum_pass_rate,
            ocr_attempts=[
                {
                    "normalizer_used": bool(ocr_result.debug.get("normalizer_used")),
                    "ocr_ms": ocr_result.duration_ms,
                    "confidence": ocr_result.confidence,
                    "prepared_size": ocr_result.debug.get("prepared_size"),
                    "fields_found": sorted(fields.keys()),
                }
            ],
        )

    def _merge_fallback_result(
        self,
        *,
        primary: MRZStageResult,
        fallback: MRZStageResult,
        invalid_fields: set[str],
        duration_ms: float,
    ) -> MRZStageResult:
        reconciled = self._reconcile_ocr_attempts(primary, fallback, duration_ms=duration_ms)
        if reconciled is not None:
            fallback = reconciled

        merged_fields = dict(primary.fields)
        merged_provenance = dict(primary.correction_provenance)
        replaced_fields: list[str] = []

        for field_name in invalid_fields:
            fallback_value = fallback.fields.get(field_name)
            if not fallback_value or not self._field_is_proven(field_name, fallback.correction_provenance):
                continue
            merged_fields[field_name] = fallback_value
            if field_name in fallback.correction_provenance:
                merged_provenance[field_name] = fallback.correction_provenance[field_name]
            replaced_fields.append(field_name)

        for line_field in ("mrz_line_1", "mrz_line_2", "personal_number"):
            if line_field not in merged_fields and line_field in fallback.fields:
                merged_fields[line_field] = fallback.fields[line_field]
                if line_field in fallback.correction_provenance:
                    merged_provenance[line_field] = fallback.correction_provenance[line_field]

        warnings = [
            warning for warning in primary.warnings
            if not any(f":{field_name}:" in warning for field_name in replaced_fields)
        ]
        warnings.extend(
            warning for warning in fallback.warnings
            if not any(f":{field_name}:" in warning for field_name in replaced_fields)
            and warning not in warnings
        )

        raw_text = fallback.raw_text if replaced_fields and fallback.raw_text else primary.raw_text
        corrected_mrz_text = fallback.corrected_mrz_text if replaced_fields and fallback.corrected_mrz_text else primary.corrected_mrz_text
        return MRZStageResult(
            fields=merged_fields,
            raw_text=raw_text,
            ocr_text="\n\n--- fallback_normalized_ocr ---\n".join(
                text for text in [primary.ocr_text, fallback.ocr_text] if text
            ) or None,
            warnings=warnings,
            duration_ms=duration_ms,
            ocr_confidence=max(primary.ocr_confidence, fallback.ocr_confidence),
            correction_provenance=merged_provenance,
            corrected_mrz_text=corrected_mrz_text,
            correction_duration_ms=primary.correction_duration_ms + fallback.correction_duration_ms,
            checksum_pass_rate=max(primary.checksum_pass_rate, fallback.checksum_pass_rate),
            ocr_attempts=[
                *primary.ocr_attempts,
                *fallback.ocr_attempts,
                {
                    "fallback_replaced_fields": sorted(replaced_fields),
                    "fallback_considered_fields": sorted(invalid_fields),
                    "reconciled_attempt_used": reconciled is not None,
                },
            ],
        )

    def _reconcile_ocr_attempts(
        self,
        primary: MRZStageResult,
        fallback: MRZStageResult,
        *,
        duration_ms: float,
    ) -> MRZStageResult | None:
        candidate_results: list[MRZStageResult] = []
        evidence_text = self._ocr_evidence_text(primary, fallback)
        for line1 in self._line1_candidates(primary, fallback):
            for line2 in self._line2_candidates(primary, fallback):
                candidate = MRZOCRResult(
                    text=f"{line1}\n{line2}",
                    confidence=max(primary.ocr_confidence, fallback.ocr_confidence),
                    duration_ms=0.0,
                    debug={
                        "normalizer_used": True,
                        "prepared_size": None,
                        "reconciled_from_attempts": True,
                    },
                )
                result = self._build_result(candidate, started=time.perf_counter())
                passport_number = result.fields.get("passport_number")
                if passport_number and passport_number not in evidence_text:
                    continue
                if not self._invalid_required_fields(result):
                    candidate_results.append(result)

        if not candidate_results:
            return None

        best = sorted(
            candidate_results,
            key=lambda result: (
                -self._passport_shape_score(result.fields.get("passport_number", "")),
                -result.checksum_pass_rate,
                -len(result.fields),
                result.corrected_mrz_text or "",
            ),
        )[0]
        return MRZStageResult(
            fields=best.fields,
            raw_text=best.raw_text,
            ocr_text=best.ocr_text,
            warnings=best.warnings,
            duration_ms=duration_ms,
            ocr_confidence=best.ocr_confidence,
            correction_provenance=best.correction_provenance,
            corrected_mrz_text=best.corrected_mrz_text,
            correction_duration_ms=best.correction_duration_ms,
            checksum_pass_rate=best.checksum_pass_rate,
            ocr_attempts=[
                {
                    "normalizer_used": True,
                    "ocr_ms": 0.0,
                    "confidence": best.ocr_confidence,
                    "prepared_size": None,
                    "fields_found": sorted(best.fields.keys()),
                    "reconciled_from_attempts": True,
                }
            ],
        )

    @staticmethod
    def _ocr_evidence_text(primary: MRZStageResult, fallback: MRZStageResult) -> str:
        return re.sub(
            r"[^A-Z0-9<]",
            "",
            "\n".join(text for text in [primary.ocr_text, fallback.ocr_text] if text).upper(),
        )

    def _line1_candidates(self, primary: MRZStageResult, fallback: MRZStageResult) -> list[str]:
        candidates: list[str] = []
        for text in (
            primary.corrected_mrz_text,
            fallback.corrected_mrz_text,
            primary.ocr_text,
            fallback.ocr_text,
        ):
            for line in self._candidate_lines(text or ""):
                if line.startswith("P"):
                    candidates.append(line[:44].ljust(44, "<"))
        return list(dict.fromkeys(candidates))

    def _line2_candidates(self, primary: MRZStageResult, fallback: MRZStageResult) -> list[str]:
        candidates: list[str] = []
        for text in (
            primary.ocr_text,
            fallback.ocr_text,
            primary.corrected_mrz_text,
            fallback.corrected_mrz_text,
        ):
            for line in self._candidate_lines(text or ""):
                if not line.startswith("P") and len(line) >= 20:
                    candidates.extend(self._line2_length_variants(line))
        return list(dict.fromkeys(candidates))[:250]

    def _candidate_lines(self, text: str) -> list[str]:
        lines = [re.sub(r"[^A-Z0-9<]", "", line.upper()) for line in text.splitlines()]
        return [line for line in lines if len(line) >= 12 and not line.startswith("---")]

    @staticmethod
    def _line2_length_variants(line: str) -> list[str]:
        variants: list[str] = []
        sanitized = line[:80]
        if len(sanitized) >= 44:
            variants.extend(sanitized[index:index + 44] for index in range(len(sanitized) - 43))
        if len(sanitized) > 44:
            overflow = min(4, len(sanitized) - 44)
            if overflow == 1:
                variants.extend(sanitized[:index] + sanitized[index + 1:] for index in range(len(sanitized)))
        if len(sanitized) == 43:
            variants = []
            for index in (0, 9, 10, 13, 21, 28, 42, 43):
                charset = (
                    "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
                    if index == 0 and sanitized[:7].isdigit()
                    else "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789<"
                )
                for char in charset:
                    variants.append((sanitized[:index] + char + sanitized[index:])[:44])
            return [variant[:44].ljust(44, "<") for variant in variants]
        if len(sanitized) < 44:
            variants.append(sanitized.ljust(44, "<"))
        return [variant[:44].ljust(44, "<") for variant in variants]

    def _invalid_required_fields(self, result: MRZStageResult) -> set[str]:
        invalid: set[str] = set()
        for field_name in CORE_FIELDS:
            if not result.fields.get(field_name):
                invalid.add(field_name)
            elif not self._field_is_proven(field_name, result.correction_provenance):
                invalid.add(field_name)
        return invalid

    @staticmethod
    def _passport_shape_score(value: str) -> int:
        return int(
            len(value) == 8
            and value[:1].isalpha()
            and value[1:].isdigit()
        )

    @staticmethod
    def _remove_unproven_fields(fields: dict[str, str], provenance: dict[str, dict[str, str | float]]) -> None:
        for field_name in list(CORE_FIELDS):
            if not Stage1MRZExtractor._field_is_proven(field_name, provenance):
                fields.pop(field_name, None)

    @staticmethod
    def _field_is_proven(field_name: str, provenance: dict[str, dict[str, str | float]]) -> bool:
        item = provenance.get(field_name)
        if not item:
            return True
        return item.get("checksum_status") not in {"fail", "review_required"}

    async def _read_mrz_text(self, image, *, normalize: bool) -> MRZOCRResult:  # type: ignore[no-untyped-def]
        try:
            import pytesseract  # noqa: F401
        except Exception as exc:
            logger.warning("stage1_mrz_tesseract_unavailable", error=str(exc))
            return MRZOCRResult(text="", confidence=0.0, duration_ms=0.0)

        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(self._ocr_reader.read, image, normalize=normalize),
                timeout=self._timeout_seconds,
            )
            logger.info(
                "stage1_mrz_ocr_completed",
                normalizer_used=normalize,
                ocr_ms=result.duration_ms,
                ocr_confidence=result.confidence,
                prepared_size=result.debug.get("prepared_size"),
            )
            return result
        except TimeoutError:
            logger.warning("stage1_mrz_ocr_timeout", timeout_seconds=self._timeout_seconds)
            return MRZOCRResult(text="", confidence=0.0, duration_ms=0.0)
        except Exception as exc:
            logger.warning("stage1_mrz_ocr_failed", error=str(exc))
            return MRZOCRResult(text="", confidence=0.0, duration_ms=0.0)

    def _prepare_mrz_crop(self, image_bytes: bytes):  # type: ignore[no-untyped-def]
        detection = self._detector.detect(image_bytes)
        if not detection.found or detection.crop is None:
            reason = detection.failure.reason if detection.failure else "unknown"
            # Camera captures often include a little useful margin, glare, or
            # shallow perspective.  Detection uncertainty must not turn into a
            # hard extraction failure: OCR can still recover a TD3 MRZ from a
            # bounded lower-page crop.  This does not rotate, warp, or alter
            # the stored visa image.
            with Image.open(io.BytesIO(image_bytes)) as raw_image:
                page = ImageOps.exif_transpose(raw_image).convert("L")
                page.thumbnail((1800, 1800))
                width, height = page.size
                if width < 240 or height < 160:
                    raise ValueError(f"MRZ region was not detected reliably: {reason}")
                fallback = page.crop((0, int(height * 0.56), width, height))
            logger.info("mrz_region_detection_fallback", reason=reason, image_size=(width, height))
            return ImageOps.autocontrast(fallback)

        prepared = ImageOps.autocontrast(detection.crop)
        logger.info(
            "mrz_region_detected",
            bbox=detection.bbox,
            score=detection.score,
            candidate_count=detection.candidate_count,
            detection_ms=detection.elapsed_ms,
        )
        return prepared

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
                if given_raw.startswith("K") and len(given_raw) > 2:
                    given_raw = given_raw[1:]

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
    def _should_replace_partial_name(current: str, candidate: str) -> bool:
        noisy_prefixes = ("IND", "NDI", "NDO", "PLIND", "PRIND", "PIND")
        return (
            current.startswith(noisy_prefixes)
            or (candidate in current and current != candidate and len(current) > len(candidate) + 2)
        )

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

def _elapsed_ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 2)
