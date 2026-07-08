"""MRZ-only passport extraction service."""

from __future__ import annotations

import time
from typing import Any

from app.application.interfaces.passport_extraction import (
    IPassportExtractionService,
    PassportExtractionResult,
)
from app.core.config.settings import get_settings
from app.core.logging.logger import get_logger
from app.infrastructure.observability import metrics
from app.infrastructure.ocr.cache import ExtractionCache
from app.infrastructure.ocr.confidence import PassportConfidenceScoringService
from app.infrastructure.ocr.mrz import TD3MRZParser
from app.infrastructure.ocr.preprocessing import OCRImagePreprocessor
from app.infrastructure.ocr.roi import ROIFallbackService
from app.infrastructure.ocr.roi.service import ROIFallbackResult
from app.infrastructure.ocr.stage1_extractor import CORE_FIELDS, Stage1MRZExtractor, StageTiming
from app.infrastructure.ocr.versioning import INDIAN_TD3_DOCUMENT_PROFILE
from app.infrastructure.validation.passport_field_validator import PassportFieldValidator

logger = get_logger(__name__)


class PassportExtractionService(IPassportExtractionService):
    """Minimal extraction engine that reads and parses only the MRZ strip."""

    def __init__(
        self,
        *,
        image_preprocessor: OCRImagePreprocessor | None = None,
        mrz_extractor: Stage1MRZExtractor | None = None,
        roi_fallback: ROIFallbackService | None = None,
        cache: ExtractionCache | None = None,
    ) -> None:
        settings = get_settings()
        self._mrz_settings = settings.mrz
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

        normalized_started = time.perf_counter()
        normalized = self._preprocessor.normalize(file_content)
        timings.append(StageTiming("image_normalization", self._elapsed_ms(normalized_started)))

        quality_started = time.perf_counter()
        quality = self._preprocessor.assess_quality(normalized)
        timings.append(StageTiming("image_quality_assessment", self._elapsed_ms(quality_started)))

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
        validation = self._validator.validate(fields, mrz_warnings=mrz_result.warnings)
        invalid_fields = self._invalid_fields(fields, validation, mrz_result.correction_provenance)
        roi_result = await self._roi_fallback.extract(normalized, invalid_fields)
        if roi_result.attempted_fields:
            timings.append(
                StageTiming(
                    "roi_fallback",
                    roi_result.duration_ms,
                    {
                        "attempted_fields": roi_result.attempted_fields,
                        "recovered_fields": roi_result.recovered_fields,
                    },
                )
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
            "name": "mrz_only",
            "document_profile": INDIAN_TD3_DOCUMENT_PROFILE,
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
        await self._cache.set(file_content, result)
        logger.info(
            "mrz_only_passport_extraction_completed",
            filename=filename,
            confidence=confidence.overall,
            validation_status=validation.status,
            total_ms=total_ms,
        )
        return result

    def _merge_fields(
        self,
        *,
        fields: dict[str, str],
        validation: Any,
        mrz_ocr_text: str | None,
        corrected_mrz_text: str | None,
        correction_provenance: dict[str, dict[str, str | float]],
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
        correction_provenance: dict[str, dict[str, str | float]],
    ) -> set[str]:
        invalid = {field for field in CORE_FIELDS if not fields.get(field)}
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
        correction_provenance: dict[str, dict[str, str | float]],
        invalid_fields: set[str],
        roi_result: ROIFallbackResult,
    ) -> tuple[dict[str, str], dict[str, str], dict[str, dict[str, object]]]:
        merged_fields = dict(fields)
        sources = self._field_sources(merged_fields, mrz_fields)
        provenance: dict[str, dict[str, object]] = dict(correction_provenance)

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
    def _elapsed_ms(started: float) -> float:
        return round((time.perf_counter() - started) * 1000, 2)
