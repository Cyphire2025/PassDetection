"""Enterprise OCR pipeline that preserves the public extraction contract."""

from __future__ import annotations

import asyncio
import inspect
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from app.application.interfaces.passport_extraction import PassportExtractionResult
from app.core.logging.logger import get_logger
from app.infrastructure.observability import metrics
from app.infrastructure.ocr.cache import ExtractionCache
from app.infrastructure.ocr.orchestration.diagnostics import PipelineTrace, ProcessingBudget
from app.infrastructure.ocr.preprocessing import OCRImagePreprocessor

logger = get_logger(__name__)


@dataclass(frozen=True)
class LocalExtractionResult:
    fields: dict[str, str]
    mrz_raw: str | None
    warnings: list[str]
    ocr_text: str | None
    evidence: dict[str, Any] = field(default_factory=dict)
    engines_used: tuple[str, ...] = ()
    preprocessing_path: str = "normalized"
    early_exit_reason: str | None = None


class ConfidenceScorer(Protocol):
    def score(self, **kwargs: Any) -> Any: ...


class FieldValidator(Protocol):
    def validate(self, fields: dict[str, str], *, mrz_warnings: list[str]) -> Any: ...


class ExtractionPipeline:
    """Coordinates preprocessing, local evidence, fallback routing, and scoring."""

    def __init__(
        self,
        *,
        preprocessor: OCRImagePreprocessor,
        extract_local: Callable[[bytes, str], Awaitable[LocalExtractionResult]],
        validator: FieldValidator,
        scorer: ConfidenceScorer,
        should_use_fallback: Callable[[Any, float], bool],
        extract_fallback: Callable[..., Awaitable[dict[str, str]]],
        merge_fallback: Callable[[dict[str, str], dict[str, str]], dict[str, str]],
        merge_fields: Callable[[dict[str, str], str | None, Any], dict[str, Any]],
        cache: ExtractionCache | None = None,
        processing_budget_seconds: float = 5.0,
    ) -> None:
        self._preprocessor = preprocessor
        self._extract_local = extract_local
        self._validator = validator
        self._scorer = scorer
        self._should_use_fallback = should_use_fallback
        self._extract_fallback = extract_fallback
        self._merge_fallback = merge_fallback
        self._merge_fields = merge_fields
        self._cache = cache or ExtractionCache()
        self._processing_budget_seconds = processing_budget_seconds

    async def extract(
        self,
        file_content: bytes,
        *,
        filename: str,
        content_type: str,
    ) -> PassportExtractionResult:
        started = time.perf_counter()
        budget = ProcessingBudget.from_seconds(self._processing_budget_seconds)
        trace = PipelineTrace(filename=filename, content_type=content_type, budget=budget)
        cache_fingerprint = self._cache.fingerprint(file_content)
        with trace.stage("cache_lookup", **cache_fingerprint) as cache_stage:
            cached = await self._cache.get(file_content)
            cache_stage.set(cache_hit=cached is not None)
        trace.set_cache(hit=cached is not None, **cache_fingerprint)
        if cached is not None:
            diagnostics = trace.to_dict()
            metrics.record_ocr(
                duration_ms=self._elapsed_ms(started),
                confidence=cached.overall_confidence,
                fallback_used=False,
                cache_hit=True,
            )
            self._record_stage_metrics(diagnostics)
            logger.info("ocr_pipeline_cache_hit", filename=filename, confidence=cached.overall_confidence)
            score = dict(cached.confidence_score)
            score["diagnostics"] = diagnostics
            score["timing_report"] = diagnostics["timing_report"]
            score["cache"] = diagnostics["cache"]
            return PassportExtractionResult(
                extracted_fields=cached.extracted_fields,
                overall_confidence=cached.overall_confidence,
                confidence_score=score,
                mrz_raw=cached.mrz_raw,
            )

        with trace.stage("image_normalization", preprocessing_path="normalize_rgb_jpeg"):
            normalized = await asyncio.to_thread(self._preprocessor.normalize, file_content)
        with trace.stage("image_quality_assessment"):
            quality = await asyncio.to_thread(self._preprocessor.assess_quality, normalized)
        preprocessing_ms = trace.duration_ms_for("image_normalization", "image_quality_assessment")

        local_started = time.perf_counter()
        with trace.stage("local_extraction", pipeline_variant="normalized", engine_path="mrz_first") as local_stage:
            local, validation, merged, confidence = await self._run_local_pass(
                normalized,
                filename=filename,
                image_quality=quality.score,
                trace=trace,
                budget=budget,
                pipeline_variant="normalized",
            )
            local_stage.set(
                engines_used=local.engines_used,
                preprocessing_path=local.preprocessing_path,
                early_exit_reason=local.early_exit_reason,
                confidence=confidence.overall,
                validation_status=validation.status,
            )
        local_ms = self._elapsed_ms(local_started)

        fallback_used = False
        fallback_ms = 0.0
        should_use_fallback = self._should_use_fallback(validation, confidence.overall)
        if should_use_fallback:
            fallback_started = time.perf_counter()
            with trace.stage(
                "vision_fallback",
                provider="configured",
                blocking_upload=False,
                local_confidence=confidence.overall,
                validation_status=validation.status,
            ):
                fallback_fields = await self._extract_fallback(
                    normalized,
                    content_type=content_type,
                    local_fields=local.fields,
                )
            fallback_ms = self._elapsed_ms(fallback_started)
            if fallback_fields:
                local_fields = self._merge_fallback(local.fields, fallback_fields)
                fallback_used = True
                validation = self._validator.validate(local_fields, mrz_warnings=local.warnings)
                merged = self._merge_fields(local_fields, local.ocr_text, validation)
        else:
            trace.skip_stage(
                "vision_fallback",
                reason="local_result_sufficient_or_fallback_unavailable",
                local_confidence=confidence.overall,
                validation_status=validation.status,
                blocking_upload=False,
            )

        if not merged:
            merged = {
                "processing_note": (
                    "No structured fields were extracted automatically. Manual review is required."
                )
            }

        with trace.stage(
            "confidence_scoring_final",
            fallback_used=fallback_used,
            image_quality=quality.score,
            validation_status=validation.status,
        ):
            confidence = self._scorer.score(
                extracted_fields=merged,
                ocr_text=local.ocr_text,
                mrz_raw=local.mrz_raw,
                validation=validation,
                evidence=local.evidence,
                image_quality=quality.score,
                fallback_used=fallback_used,
            )
        timings = {
            "preprocessing_ms": preprocessing_ms,
            "local_extraction_ms": local_ms,
            "fallback_ms": fallback_ms,
            "total_ms": trace.elapsed_ms(),
        }
        diagnostics = trace.to_dict()
        score_payload = confidence.to_dict()
        score_payload["image_quality"] = quality.to_dict()
        score_payload["evidence"] = local.evidence
        score_payload["timings"] = timings
        score_payload["cache"] = diagnostics["cache"]
        score_payload["diagnostics"] = diagnostics
        score_payload["timing_report"] = diagnostics["timing_report"]
        score_payload["adaptive_pipeline"] = {
            "initial_variant": "normalized",
            "document_profile": diagnostics["document_profile"],
            "processing_budget": diagnostics["budget"],
        }
        logger.info(
            "ocr_pipeline_completed",
            filename=filename,
            confidence=confidence.overall,
            fallback_used=fallback_used,
            early_exit=diagnostics["early_exit"],
            **timings,
        )
        result = PassportExtractionResult(
            extracted_fields=merged,
            overall_confidence=confidence.overall,
            confidence_score=score_payload,
            mrz_raw=local.mrz_raw,
        )
        metrics.record_ocr(
            duration_ms=timings["total_ms"],
            confidence=confidence.overall,
            fallback_used=fallback_used,
        )
        self._record_stage_metrics(diagnostics)
        await self._cache.set(file_content, result)
        return result

    @staticmethod
    def _elapsed_ms(started: float) -> float:
        return round((time.perf_counter() - started) * 1000, 2)

    async def _run_local_pass(
        self,
        image_bytes: bytes,
        *,
        filename: str,
        image_quality: float,
        trace: PipelineTrace,
        budget: ProcessingBudget,
        pipeline_variant: str,
    ) -> tuple[LocalExtractionResult, Any, dict[str, Any], Any]:
        local = await self._extract_local_with_context(
            image_bytes,
            filename,
            trace=trace,
            budget=budget,
        )
        with trace.stage("field_validation", pipeline_variant=pipeline_variant):
            validation = self._validator.validate(local.fields, mrz_warnings=local.warnings)
        with trace.stage("field_merge", pipeline_variant=pipeline_variant):
            merged = self._merge_fields(local.fields, local.ocr_text, validation)
        with trace.stage(
            "confidence_scoring",
            pipeline_variant=pipeline_variant,
            image_quality=image_quality,
            fallback_used=False,
        ):
            confidence = self._scorer.score(
                extracted_fields=merged,
                ocr_text=local.ocr_text,
                mrz_raw=local.mrz_raw,
                validation=validation,
                evidence=local.evidence,
                image_quality=image_quality,
                fallback_used=False,
            )
        return local, validation, merged, confidence

    async def _extract_local_with_context(
        self,
        image_bytes: bytes,
        filename: str,
        *,
        trace: PipelineTrace,
        budget: ProcessingBudget,
    ) -> LocalExtractionResult:
        parameters = inspect.signature(self._extract_local).parameters
        accepts_context = (
            "diagnostics" in parameters
            or "budget" in parameters
            or any(parameter.kind == inspect.Parameter.VAR_KEYWORD for parameter in parameters.values())
        )
        if accepts_context:
            return await self._extract_local(
                image_bytes,
                filename,
                diagnostics=trace,
                budget=budget,
            )
        return await self._extract_local(image_bytes, filename)

    @staticmethod
    def _record_stage_metrics(diagnostics: dict[str, Any]) -> None:
        for stage in diagnostics.get("stages", []):
            if not isinstance(stage, dict):
                continue
            stage_name = stage.get("name")
            duration_ms = stage.get("duration_ms")
            if isinstance(stage_name, str) and isinstance(duration_ms, int | float):
                metrics.record_ocr_stage(stage=stage_name, duration_ms=float(duration_ms))
