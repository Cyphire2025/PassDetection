"""One-pass visual OCR fallback for missing passport fields."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field

from app.core.config.settings import get_settings
from app.core.logging.logger import get_logger
from app.infrastructure.ocr.data_page_ocr import (
    SUPPORTED_VISUAL_FIELDS,
    DataPageOCRReader,
    ParsedVisualField,
    PassportDataPageParser,
)

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
    """Runs one visual OCR read, then parses every requested field from it."""

    def __init__(
        self,
        *,
        reader: DataPageOCRReader | None = None,
        parser: PassportDataPageParser | None = None,
    ) -> None:
        self._reader = reader or DataPageOCRReader()
        self._parser = parser or PassportDataPageParser()

    async def extract(
        self,
        image_bytes: bytes,
        requested_fields: set[str],
        *,
        overall_timeout_seconds: float | None = None,
    ) -> ROIFallbackResult:
        started = time.perf_counter()
        attempted = sorted(set(SUPPORTED_VISUAL_FIELDS) & requested_fields)
        if not attempted:
            return ROIFallbackResult({}, {}, [], [], self._elapsed_ms(started))

        configured_timeout = get_settings().roi_field_timeout_seconds
        timeout_seconds = (
            configured_timeout
            if overall_timeout_seconds is None
            else min(configured_timeout, overall_timeout_seconds)
        )
        if timeout_seconds <= 0:
            return self._empty_timeout_result(attempted, started)

        try:
            async with asyncio.timeout(timeout_seconds):
                ocr_result = await asyncio.to_thread(
                    self._reader.read,
                    image_bytes,
                    timeout_seconds=timeout_seconds,
                )
        except TimeoutError:
            logger.warning(
                "data_page_ocr_timeout",
                timeout_seconds=round(timeout_seconds, 3),
            )
            return self._empty_timeout_result(attempted, started)
        except Exception as exc:
            logger.warning(
                "data_page_ocr_failed",
                error_type=type(exc).__name__,
            )
            return ROIFallbackResult(
                {},
                {},
                attempted,
                [],
                self._elapsed_ms(started),
                debug={
                    "ocr_invocations": 1,
                    "budget_exhausted": False,
                    "failure": "ocr_unavailable",
                },
            )

        parsed = self._parser.parse(ocr_result, set(attempted))
        fields = {
            field_name: result.value
            for field_name, result in parsed.items()
            if result.value
        }
        provenance = {
            field_name: self._provenance(result)
            for field_name, result in parsed.items()
            if result.value
        }
        return ROIFallbackResult(
            fields=fields,
            provenance=provenance,
            attempted_fields=attempted,
            recovered_fields=sorted(fields),
            duration_ms=self._elapsed_ms(started),
            debug={
                "ocr_invocations": 1,
                "budget_exhausted": False,
                "line_count": len(ocr_result.lines),
                "ocr_ms": ocr_result.duration_ms,
            },
        )

    @staticmethod
    def _provenance(result: ParsedVisualField) -> dict[str, object]:
        return {
            "corrected_value": result.value,
            "correction_reason": "validated_single_pass_data_page_ocr",
            "checksum_status": "not_applicable",
            "confidence": result.confidence,
            "source": result.source,
            "debug": result.debug,
        }

    @classmethod
    def _empty_timeout_result(
        cls,
        attempted: list[str],
        started: float,
    ) -> ROIFallbackResult:
        return ROIFallbackResult(
            {},
            {},
            attempted,
            [],
            cls._elapsed_ms(started),
            debug={
                "ocr_invocations": 1,
                "budget_exhausted": True,
                "timed_out_fields": attempted,
            },
        )

    @staticmethod
    def _elapsed_ms(started: float) -> float:
        return round((time.perf_counter() - started) * 1000, 2)
