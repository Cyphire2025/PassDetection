"""Stage 1 passport extraction service.

This module intentionally replaces the previous overbuilt extraction engine
with a deterministic MRZ-first path plus targeted OCR for missing fields.
Gemini is used only as a final verifier, never as the primary extractor.
"""

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
from app.infrastructure.ocr.gemini_verifier import GeminiPassportVerifier, GeminiVerificationResult
from app.infrastructure.ocr.mrz import TD3MRZParser
from app.infrastructure.ocr.preprocessing import OCRImagePreprocessor
from app.infrastructure.ocr.stage1_extractor import (
    CORE_FIELDS,
    Stage1MRZExtractor,
    Stage1TargetedOCR,
    StageTiming,
    invalid_or_missing_fields,
)
from app.infrastructure.ocr.versioning import INDIAN_TD3_DOCUMENT_PROFILE
from app.infrastructure.validation.passport_field_validator import PassportFieldValidator

logger = get_logger(__name__)


class PassportExtractionService(IPassportExtractionService):
    """Minimal Stage 1 passport extraction engine."""

    def __init__(
        self,
        *,
        image_preprocessor: OCRImagePreprocessor | None = None,
        mrz_extractor: Stage1MRZExtractor | None = None,
        targeted_ocr: Stage1TargetedOCR | None = None,
        gemini_verifier: GeminiPassportVerifier | None = None,
        cache: ExtractionCache | None = None,
    ) -> None:
        settings = get_settings()
        self._ocr_settings = settings.ocr
        self._preprocessor = image_preprocessor or OCRImagePreprocessor()
        self._mrz_parser = TD3MRZParser()
        ocr_timeout = min(self._ocr_settings.engine_timeout_seconds, 3.0)
        self._mrz_extractor = mrz_extractor or Stage1MRZExtractor(
            preprocessor=self._preprocessor,
            parser=self._mrz_parser,
            timeout_seconds=ocr_timeout,
        )
        self._targeted_ocr = targeted_ocr or Stage1TargetedOCR(
            preprocessor=self._preprocessor,
            timeout_seconds=ocr_timeout,
        )
        self._gemini_verifier = gemini_verifier or GeminiPassportVerifier(settings.gemini)
        self._validator = PassportFieldValidator()
        self._scorer = PassportConfidenceScoringService()
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
                {"fields_found": sorted(mrz_result.fields.keys()), "mrz_found": bool(mrz_result.raw_text)},
            )
        )

        fields = dict(mrz_result.fields)
        validation = self._validator.validate(fields, mrz_warnings=mrz_result.warnings)
        targets = invalid_or_missing_fields(fields, validation.issues)

        ocr_result = await self._targeted_ocr.extract(normalized, targets)
        timings.append(
            StageTiming(
                "targeted_ocr",
                ocr_result.duration_ms,
                {"target_fields": sorted(targets), "fields_found": sorted(ocr_result.fields.keys())},
            )
        )
        fields.update({key: value for key, value in ocr_result.fields.items() if key in targets})

        validation = self._validator.validate(fields, mrz_warnings=mrz_result.warnings)
        gemini_result = await self._gemini_verifier.verify(
            image_bytes=normalized,
            content_type=content_type,
            fields=self._public_string_fields(fields),
            mrz_raw=mrz_result.raw_text,
            ocr_output=ocr_result.raw_text,
        )
        timings.append(
            StageTiming(
                "gemini_verification",
                0.0,
                {
                    "status": gemini_result.status,
                    "enabled": self._gemini_verifier.is_available,
                    "correction_count": len(gemini_result.corrections),
                    "uncertain_count": len(gemini_result.uncertain_fields),
                },
            )
        )

        fields = self._apply_safe_gemini_corrections(fields, gemini_result)
        validation = self._validator.validate(fields, mrz_warnings=mrz_result.warnings)
        merged = self._merge_fields(
            fields=fields,
            validation=validation,
            mrz_ocr_text=mrz_result.ocr_text,
            targeted_ocr_text=ocr_result.raw_text,
            gemini_result=gemini_result,
            sources=self._field_sources(fields, mrz_result.fields, ocr_result.fields, gemini_result),
        )

        evidence = self._evidence(fields, mrz_result.fields, ocr_result.fields, gemini_result)
        confidence = self._scorer.score(
            extracted_fields=merged,
            ocr_text=self._combined_ocr_text(mrz_result.ocr_text, ocr_result.raw_text),
            mrz_raw=mrz_result.raw_text,
            validation=validation,
            evidence=evidence,
            image_quality=quality.score,
            fallback_used=False,
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
            "targeted_ocr_ms": ocr_result.duration_ms,
        }
        score_payload["cache"] = diagnostics["cache"]
        score_payload["diagnostics"] = diagnostics
        score_payload["timing_report"] = diagnostics["timing_report"]
        score_payload["pipeline"] = {
            "name": "stage1_mrz_first",
            "document_profile": INDIAN_TD3_DOCUMENT_PROFILE,
            "gemini_verifier": gemini_result.status,
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
            fallback_used=False,
            cache_hit=False,
        )
        for timing in timings:
            metrics.record_ocr_stage(stage=timing.name, duration_ms=timing.duration_ms)
        await self._cache.set(file_content, result)
        logger.info(
            "stage1_passport_extraction_completed",
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
        targeted_ocr_text: dict[str, str],
        gemini_result: GeminiVerificationResult,
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
        merged["gemini_verification"] = gemini_result.to_dict()
        if mrz_ocr_text:
            merged["raw_mrz_ocr_text"] = mrz_ocr_text[:1000]
        if targeted_ocr_text:
            merged["targeted_ocr_text"] = {
                key: value[:300]
                for key, value in targeted_ocr_text.items()
                if value
            }
        if not any(merged.get(field) for field in CORE_FIELDS):
            merged["processing_note"] = "No structured fields were extracted automatically. Manual review is required."
        return merged

    def _apply_safe_gemini_corrections(
        self,
        fields: dict[str, str],
        gemini_result: GeminiVerificationResult,
    ) -> dict[str, str]:
        if gemini_result.status != "completed" or not gemini_result.corrections:
            return fields
        corrected = dict(fields)
        for field_name, value in gemini_result.corrections.items():
            if field_name not in corrected:
                continue
            if not isinstance(value, str) or not value.strip():
                continue
            candidate = value.strip().upper()
            validation = self._validator.validate({**corrected, field_name: candidate}, mrz_warnings=[])
            invalid_fields = {issue.field for issue in validation.issues}
            if field_name not in invalid_fields:
                corrected[field_name] = candidate
        return corrected

    def _field_sources(
        self,
        fields: dict[str, str],
        mrz_fields: dict[str, str],
        ocr_fields: dict[str, str],
        gemini_result: GeminiVerificationResult,
    ) -> dict[str, str]:
        sources: dict[str, str] = {}
        for field_name in fields:
            if field_name in gemini_result.corrections:
                sources[field_name] = "gemini_correction"
            elif field_name in ocr_fields:
                sources[field_name] = "targeted_ocr"
            elif field_name in mrz_fields:
                sources[field_name] = "mrz"
        return sources

    def _evidence(
        self,
        fields: dict[str, str],
        mrz_fields: dict[str, str],
        ocr_fields: dict[str, str],
        gemini_result: GeminiVerificationResult,
    ) -> dict[str, dict[str, Any]]:
        evidence: dict[str, dict[str, Any]] = {}
        for field_name in fields:
            source = "targeted_ocr" if field_name in ocr_fields else "mrz" if field_name in mrz_fields else "unknown"
            confidence = 0.98 if source == "mrz" else 0.74 if source == "targeted_ocr" else 0.65
            status = (gemini_result.field_results.get(field_name) or {}).get("status")
            agreement = 1.0 if status == "confirmed" else 0.75 if status in {None, "uncertain"} else 0.6
            evidence[field_name] = {
                "confidence": confidence,
                "agreement": agreement,
                "supporting_evidence": [{"ocr_engine": source, "value": fields[field_name]}],
            }
        return evidence

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
    def _combined_ocr_text(mrz_text: str | None, targeted_text: dict[str, str]) -> str | None:
        parts = [mrz_text or ""]
        parts.extend(f"{key}: {value}" for key, value in targeted_text.items() if value)
        combined = "\n".join(part for part in parts if part.strip()).strip()
        return combined or None

    @staticmethod
    def _public_string_fields(fields: dict[str, str]) -> dict[str, str]:
        return {key: value for key, value in fields.items() if isinstance(value, str) and value.strip()}

    @staticmethod
    def _elapsed_ms(started: float) -> float:
        return round((time.perf_counter() - started) * 1000, 2)
