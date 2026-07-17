"""Orchestrates field-specific ROI OCR fallbacks."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Iterable
from dataclasses import dataclass, field

from app.core.config.settings import get_settings
from app.core.logging.logger import get_logger
from app.infrastructure.ocr.roi.base import ROIExtractionResult, ROIFieldExtractor
from app.infrastructure.ocr.roi.common import ROIImageTools
from app.infrastructure.ocr.roi.extractors.date_of_birth_roi import DateOfBirthROIExtractor
from app.infrastructure.ocr.roi.extractors.date_of_expiry_roi import DateOfExpiryROIExtractor
from app.infrastructure.ocr.roi.extractors.date_of_issue_roi import DateOfIssueROIExtractor
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
        registered: list[ROIFieldExtractor] = list(extractors) if extractors is not None else [
            PassportNumberROIExtractor(),
            SurnameROIExtractor(),
            GivenNamesROIExtractor(),
            DateOfBirthROIExtractor(),
            DateOfExpiryROIExtractor(),
            DateOfIssueROIExtractor(),
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

        settings = get_settings()
        timeout_seconds = settings.roi_field_timeout_seconds
        semaphore = asyncio.Semaphore(settings.roi_max_concurrency)

        async def extract_field(
            field_name: str,
        ) -> ROIExtractionResult | None:
            try:
                async with semaphore:
                    # Each worker owns its decoded image. If a native OCR call
                    # outlives the await timeout, no shared PIL object is
                    # closed underneath that worker.
                    return await asyncio.wait_for(
                        asyncio.to_thread(
                            self._extract_one,
                            self._extractors[field_name],
                            image_bytes,
                        ),
                        timeout=timeout_seconds,
                    )
            except TimeoutError:
                logger.warning(
                    "roi_fallback_field_timeout",
                    field=field_name,
                    timeout_seconds=timeout_seconds,
                )
                return None
            except Exception as exc:
                logger.warning(
                    "roi_fallback_field_failed",
                    field=field_name,
                    error_type=type(exc).__name__,
                )
            return None

        # Field crops are independent. A bounded fan-out prevents the previous
        # worst case of eight sequential timeouts while keeping CPU use
        # predictable on the OCR worker.
        results = await asyncio.gather(
            *(extract_field(field_name) for field_name in attempted)
        )
        for result in results:
            if result is None:
                continue
            fields[result.field_name] = result.value
            provenance[result.field_name] = self._provenance(result)

        return ROIFallbackResult(
            fields=fields,
            provenance=provenance,
            attempted_fields=attempted,
            recovered_fields=sorted(fields),
            duration_ms=self._elapsed_ms(started),
        )

    @staticmethod
    def _extract_one(
        extractor: ROIFieldExtractor,
        image_bytes: bytes,
    ) -> ROIExtractionResult | None:
        image = ROIImageTools.open_image(image_bytes)
        try:
            return extractor.extract(image)
        finally:
            image.close()

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
