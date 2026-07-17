"""Bounded MRZ plus single-pass visual passport extraction service."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Mapping
from typing import Any

from app.application.interfaces.passport_extraction import (
    IPassportExtractionService,
    PassportExtractionResult,
)
from app.core.config.settings import get_settings
from app.core.logging.logger import get_logger
from app.core.time_budget import TimeBudget
from app.domain.value_objects.passport_fields import normalize_extracted_passport_dates
from app.infrastructure.observability import metrics
from app.infrastructure.ocr.cache import ExtractionCache
from app.infrastructure.ocr.confidence import PassportConfidenceScoringService
from app.infrastructure.ocr.mrz import TD3MRZParser
from app.infrastructure.ocr.preprocessing import ImageQualityAssessment, OCRImagePreprocessor
from app.infrastructure.ocr.roi import ROIFallbackService
from app.infrastructure.ocr.roi.service import ROIFallbackResult
from app.infrastructure.ocr.stage1_extractor import (
    CORE_FIELDS,
    MRZStageResult,
    Stage1MRZExtractor,
    StageTiming,
)
from app.infrastructure.ocr.versioning import INDIAN_TD3_DOCUMENT_PROFILE
from app.infrastructure.validation.passport_field_validator import PassportFieldValidator

logger = get_logger(__name__)


class PassportExtractionService(IPassportExtractionService):
    """Runs one MRZ read and at most one visual data-page read."""

    def __init__(
        self,
        *,
        image_preprocessor: OCRImagePreprocessor | None = None,
        mrz_extractor: Stage1MRZExtractor | None = None,
        roi_fallback: ROIFallbackService | None = None,
        cache: ExtractionCache | None = None,
        local_timeout_seconds: float | None = None,
    ) -> None:
        settings = get_settings()
        self._mrz_settings = settings.mrz
        configured_timeout = (
            settings.passport_local_extraction_timeout_seconds
            if local_timeout_seconds is None
            else local_timeout_seconds
        )
        # This is a safety limit, not only a default. A bad deployment value
        # must never make local OCR consume the whole first-pass job deadline.
        self._local_timeout_seconds = min(10.0, max(0.1, float(configured_timeout)))
        self._preprocessor = image_preprocessor or OCRImagePreprocessor()
        self._mrz_parser = TD3MRZParser()
        self._mrz_extractor = mrz_extractor or Stage1MRZExtractor(
            preprocessor=self._preprocessor,
            parser=self._mrz_parser,
            timeout_seconds=self._mrz_settings.timeout_seconds,
        )
        self._validator = PassportFieldValidator()
        self._scorer = PassportConfidenceScoringService()
        self._roi_fallback = roi_fallback or ROIFallbackService()
        self._cache = cache or ExtractionCache()

    async def extract(self, file_content: bytes, *, filename: str, content_type: str) -> PassportExtractionResult:
        started = time.perf_counter()
        timings: list[StageTiming] = []
        cache_fingerprint = self._cache.fingerprint(file_content)
        budget = TimeBudget.start(self._local_timeout_seconds)
        reserve_seconds = min(0.25, self._local_timeout_seconds * 0.1)
        working_timeout = max(0.01, budget.remaining() - reserve_seconds)
        current_stage = "cache_lookup"
        budget_exhausted = False
        quality = self._empty_quality()
        mrz_result = self._empty_mrz_result()
        roi_result = self._empty_roi_result()
        fields: dict[str, str] = {}
        invalid_fields = set(CORE_FIELDS) | {"date_of_issue"}

        try:
            async with asyncio.timeout(working_timeout):
                cache_started = time.perf_counter()
                cached = await self._cache.get(file_content)
                timings.append(
                    StageTiming(
                        "cache_lookup",
                        self._elapsed_ms(cache_started),
                        {"cache_hit": cached is not None},
                    )
                )
                if cached is not None:
                    score = dict(cached.confidence_score)
                    score["cache"] = {"hit": True, **cache_fingerprint}
                    return PassportExtractionResult(
                        extracted_fields=cached.extracted_fields,
                        overall_confidence=cached.overall_confidence,
                        confidence_score=score,
                        mrz_raw=cached.mrz_raw,
                    )

                current_stage = "image_normalization"
                normalized_started = time.perf_counter()
                normalized = await asyncio.to_thread(self._preprocessor.normalize, file_content)
                timings.append(
                    StageTiming("image_normalization", self._elapsed_ms(normalized_started))
                )

                current_stage = "image_quality_assessment"
                quality_started = time.perf_counter()
                quality = await asyncio.to_thread(self._preprocessor.assess_quality, normalized)
                timings.append(
                    StageTiming("image_quality_assessment", self._elapsed_ms(quality_started))
                )

                current_stage = "mrz_extraction"
                mrz_result = await self._mrz_extractor.extract(normalized)
                timings.append(
                    StageTiming(
                        "mrz_extraction",
                        mrz_result.duration_ms,
                        {
                            "fields_found": sorted(mrz_result.fields.keys()),
                            "mrz_found": bool(mrz_result.raw_text),
                            "correction_ms": mrz_result.correction_duration_ms,
                            "checksum_pass_rate": mrz_result.checksum_pass_rate,
                        },
                    )
                )

                fields = dict(mrz_result.fields)
                validation = self._validator.validate(
                    fields,
                    mrz_warnings=mrz_result.warnings,
                )
                invalid_fields = self._invalid_fields(
                    fields,
                    validation,
                    mrz_result.correction_provenance,
                )
                current_stage = "roi_fallback"
                roi_timeout = max(0.001, budget.remaining() - reserve_seconds)
                roi_result = await self._roi_fallback.extract(
                    normalized,
                    invalid_fields,
                    overall_timeout_seconds=roi_timeout,
                )
                if roi_result.attempted_fields:
                    timings.append(
                        StageTiming(
                            "roi_fallback",
                            roi_result.duration_ms,
                            {
                                "attempted_fields": roi_result.attempted_fields,
                                "recovered_fields": roi_result.recovered_fields,
                                "budget_exhausted": bool(
                                    roi_result.debug.get("budget_exhausted")
                                ),
                            },
                        )
                    )
                budget_exhausted = bool(roi_result.debug.get("budget_exhausted"))
        except TimeoutError:
            budget_exhausted = True
            timings.append(
                StageTiming(
                    f"{current_stage}_timeout",
                    self._elapsed_ms(started),
                    {"budget_exhausted": True},
                )
            )
            logger.warning(
                "passport_local_extraction_budget_exhausted",
                stage=current_stage,
                timeout_seconds=self._local_timeout_seconds,
                fields_found_count=len(fields),
            )

        fields, sources, correction_provenance = self._merge_roi_fields(
            fields=fields,
            mrz_fields=mrz_result.fields,
            correction_provenance=mrz_result.correction_provenance,
            invalid_fields=invalid_fields,
            roi_result=roi_result,
        )
        validation = self._validator.validate(fields, mrz_warnings=mrz_result.warnings)
        merged = self._merge_fields(
            fields=fields,
            validation=validation,
            mrz_ocr_text=mrz_result.ocr_text,
            corrected_mrz_text=mrz_result.corrected_mrz_text,
            correction_provenance=correction_provenance,
            sources=sources,
        )
        merged = normalize_extracted_passport_dates(merged)

        evidence = self._evidence(fields, sources)
        confidence = self._scorer.score(
            extracted_fields=merged,
            ocr_text=mrz_result.ocr_text,
            mrz_raw=mrz_result.raw_text,
            validation=validation,
            evidence=evidence,
            image_quality=quality.score,
            fallback_used=bool(roi_result.recovered_fields),
        )
        total_ms = self._elapsed_ms(started)
        diagnostics = self._diagnostics(
            filename=filename,
            content_type=content_type,
            total_ms=total_ms,
            timings=timings,
            cache={**cache_fingerprint, "hit": False},
        )
        score_payload = confidence.to_dict()
        score_payload["image_quality"] = quality.to_dict()
        score_payload["evidence"] = evidence
        score_payload["timings"] = {
            "total_ms": total_ms,
            "mrz_extraction_ms": mrz_result.duration_ms,
            "mrz_correction_ms": mrz_result.correction_duration_ms,
            "roi_fallback_ms": roi_result.duration_ms,
        }
        score_payload["cache"] = diagnostics["cache"]
        score_payload["diagnostics"] = diagnostics
        score_payload["timing_report"] = diagnostics["timing_report"]
        score_payload["pipeline"] = {
            "name": "mrz_plus_single_pass_visual",
            "document_profile": INDIAN_TD3_DOCUMENT_PROFILE,
            "local_budget": {
                "timeout_seconds": self._local_timeout_seconds,
                "exhausted": budget_exhausted,
            },
            "roi_fallback": {
                "attempted_fields": roi_result.attempted_fields,
                "recovered_fields": roi_result.recovered_fields,
            },
        }

        result = PassportExtractionResult(
            extracted_fields=merged,
            overall_confidence=confidence.overall,
            confidence_score=score_payload,
            mrz_raw=mrz_result.raw_text,
        )
        metrics.record_ocr(
            duration_ms=total_ms,
            confidence=confidence.overall,
            fallback_used=bool(roi_result.recovered_fields),
            cache_hit=False,
        )
        for timing in timings:
            metrics.record_ocr_stage(stage=timing.name, duration_ms=timing.duration_ms)
        if not budget_exhausted and budget.has_time(0.001):
            try:
                async with asyncio.timeout(budget.remaining()):
                    await self._cache.set(file_content, result)
            except TimeoutError:
                logger.info("passport_extraction_cache_write_skipped", reason="budget_exhausted")
        logger.info(
            "mrz_and_single_pass_ocr_extraction_completed",
            confidence=confidence.overall,
            validation_status=validation.status,
            total_ms=total_ms,
            budget_exhausted=budget_exhausted,
        )
        return result

    def _merge_fields(
        self,
        *,
        fields: dict[str, str],
        validation: Any,
        mrz_ocr_text: str | None,
        corrected_mrz_text: str | None,
        correction_provenance: Mapping[str, Mapping[str, object]],
        sources: dict[str, str],
    ) -> dict[str, Any]:
        merged: dict[str, Any] = dict(fields)
        merged["field_validation"] = {
            "status": validation.status,
            "issues": [
                {
                    "field": issue.field,
                    "message": issue.message,
                    "severity": issue.severity,
                }
                for issue in validation.issues
            ],
        }
        merged["extraction_sources"] = sources
        if mrz_ocr_text:
            merged["raw_mrz_ocr_text"] = mrz_ocr_text[:1000]
        if corrected_mrz_text:
            merged["corrected_mrz_text"] = corrected_mrz_text[:1000]
        if correction_provenance:
            merged["field_provenance"] = correction_provenance
        if not any(merged.get(field) for field in CORE_FIELDS):
            merged["processing_note"] = "No MRZ fields were extracted automatically."
        return merged

    def _field_sources(self, fields: dict[str, str], mrz_fields: dict[str, str]) -> dict[str, str]:
        return {field_name: "mrz" for field_name in fields if field_name in mrz_fields}

    def _evidence(self, fields: dict[str, str], sources: dict[str, str]) -> dict[str, dict[str, Any]]:
        evidence: dict[str, dict[str, Any]] = {}
        for field_name in fields:
            source = sources.get(field_name, "unknown")
            evidence[field_name] = {
                "confidence": 0.98 if source == "mrz" else 0.86 if source.startswith("roi") else 0.65,
                "agreement": 1.0,
                "supporting_evidence": [{"ocr_engine": source, "value": fields[field_name]}],
            }
        return evidence

    def _invalid_fields(
        self,
        fields: dict[str, str],
        validation: Any,
        correction_provenance: Mapping[str, Mapping[str, object]],
    ) -> set[str]:
        invalid = {field for field in CORE_FIELDS if not fields.get(field)}
        # Date of issue is not encoded in TD3 MRZ data. Always request its
        # label-anchored visual ROI when it is not already present.
        if not fields.get("date_of_issue"):
            invalid.add("date_of_issue")
        invalid.update(issue.field for issue in validation.issues if issue.field in CORE_FIELDS)
        for field_name, provenance in correction_provenance.items():
            if field_name in CORE_FIELDS and provenance.get("checksum_status") in {"fail", "review_required"}:
                invalid.add(field_name)
        return invalid

    def _merge_roi_fields(
        self,
        *,
        fields: dict[str, str],
        mrz_fields: dict[str, str],
        correction_provenance: Mapping[str, Mapping[str, object]],
        invalid_fields: set[str],
        roi_result: ROIFallbackResult,
    ) -> tuple[dict[str, str], dict[str, str], dict[str, dict[str, object]]]:
        merged_fields = dict(fields)
        sources = self._field_sources(merged_fields, mrz_fields)
        provenance = {
            field_name: dict(field_provenance)
            for field_name, field_provenance in correction_provenance.items()
        }

        for field_name, value in roi_result.fields.items():
            if field_name not in invalid_fields:
                continue
            if field_name in merged_fields and field_name not in invalid_fields:
                continue
            if not value:
                continue
            merged_fields[field_name] = value
            if field_name in roi_result.provenance:
                provenance[field_name] = roi_result.provenance[field_name]
            sources[field_name] = str(provenance.get(field_name, {}).get("source") or "roi")

        return merged_fields, sources, provenance

    def _diagnostics(
        self,
        *,
        filename: str,
        content_type: str,
        total_ms: float,
        timings: list[StageTiming],
        cache: dict[str, Any],
    ) -> dict[str, Any]:
        stages = [timing.to_dict() for timing in timings]
        return {
            "filename": filename,
            "content_type": content_type,
            "total_duration_ms": total_ms,
            "document_profile": INDIAN_TD3_DOCUMENT_PROFILE,
            "cache": cache,
            "stages": stages,
            "timing_report": stages,
        }

    @staticmethod
    def _empty_quality() -> ImageQualityAssessment:
        return ImageQualityAssessment(
            score=0.0,
            sharpness=0.0,
            brightness=0.0,
            contrast=0.0,
            width=0,
            height=0,
        )

    @staticmethod
    def _empty_mrz_result() -> MRZStageResult:
        return MRZStageResult(
            fields={},
            raw_text=None,
            ocr_text=None,
            warnings=[],
            duration_ms=0.0,
        )

    @staticmethod
    def _empty_roi_result() -> ROIFallbackResult:
        return ROIFallbackResult(
            fields={},
            provenance={},
            attempted_fields=[],
            recovered_fields=[],
            duration_ms=0.0,
        )

    @staticmethod
    def _elapsed_ms(started: float) -> float:
        return round((time.perf_counter() - started) * 1000, 2)
