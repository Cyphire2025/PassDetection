"""Orchestrates field-specific ROI OCR fallbacks."""

from __future__ import annotations

import time
from collections.abc import Iterable
from dataclasses import dataclass, field

from app.core.logging.logger import get_logger
from app.infrastructure.ocr.roi.base import ROIExtractionResult, ROIFieldExtractor
from app.infrastructure.ocr.roi.common import ROIImageTools
from app.infrastructure.ocr.roi.extractors.date_of_birth_roi import DateOfBirthROIExtractor
from app.infrastructure.ocr.roi.extractors.date_of_expiry_roi import DateOfExpiryROIExtractor
from app.infrastructure.ocr.roi.extractors.given_names_roi import GivenNamesROIExtractor
from app.infrastructure.ocr.roi.extractors.nationality_roi import NationalityROIExtractor
from app.infrastructure.ocr.roi.extractors.passport_number_roi import PassportNumberROIExtractor
from app.infrastructure.ocr.roi.extractors.sex_roi import SexROIExtractor
from app.infrastructure.ocr.roi.extractors.surname_roi import SurnameROIExtractor

logger = get_logger(__name__)


@dataclass(frozen=True)
class ROIFallbackResult:
    fields: dict[str, str]
    provenance: dict[str, dict[str, object]]
    attempted_fields: list[str]
    recovered_fields: list[str]
    duration_ms: float
    debug: dict[str, object] = field(default_factory=dict)


class ROIFallbackService:
    """Runs only requested field extractors against the full passport image."""

    def __init__(self, extractors: Iterable[ROIFieldExtractor] | None = None) -> None:
        registered = list(extractors) if extractors is not None else [
            PassportNumberROIExtractor(),
            SurnameROIExtractor(),
            GivenNamesROIExtractor(),
            DateOfBirthROIExtractor(),
            DateOfExpiryROIExtractor(),
            SexROIExtractor(),
            NationalityROIExtractor(),
        ]
        self._extractors = {extractor.field_name: extractor for extractor in registered}

    async def extract(self, image_bytes: bytes, requested_fields: set[str]) -> ROIFallbackResult:
        started = time.perf_counter()
        fields: dict[str, str] = {}
        provenance: dict[str, dict[str, object]] = {}
        attempted = sorted(field for field in requested_fields if field in self._extractors)
        if not attempted:
            return ROIFallbackResult({}, {}, [], [], self._elapsed_ms(started))

        try:
            image = ROIImageTools.open_image(image_bytes)
        except Exception as exc:
            logger.warning("roi_fallback_image_open_failed", error=str(exc))
            return ROIFallbackResult({}, {}, attempted, [], self._elapsed_ms(started), {"error": str(exc)})

        try:
            for field_name in attempted:
                result = self._extractors[field_name].extract(image)
                if result is None:
                    continue
                fields[result.field_name] = result.value
                provenance[result.field_name] = self._provenance(result)
        finally:
            image.close()

        return ROIFallbackResult(
            fields=fields,
            provenance=provenance,
            attempted_fields=attempted,
            recovered_fields=sorted(fields),
            duration_ms=self._elapsed_ms(started),
        )

    @staticmethod
    def _provenance(result: ROIExtractionResult) -> dict[str, object]:
        return {
            "original_ocr_value": result.debug.get("raw_text", result.value),
            "corrected_value": result.value,
            "correction_reason": "validated_roi_ocr",
            "checksum_status": "not_applicable",
            "confidence": result.confidence,
            "source": result.source,
            "debug": result.debug,
        }

    @staticmethod
    def _elapsed_ms(started: float) -> float:
        return round((time.perf_counter() - started) * 1000, 2)
