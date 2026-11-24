"""Second-pass Gemini verification after a client submits reviewed fields."""

from __future__ import annotations

import asyncio
import json
import random
import time
from collections.abc import Callable
from typing import Any

import httpx

from app.application.interfaces.post_submission_verification import (
    POST_SUBMISSION_PASSPORT_FIELDS,
    IPostSubmissionPassportVerificationService,
    PostSubmissionFieldVerdict,
    PostSubmissionVerificationDecision,
    PostSubmissionVerificationResult,
)
from app.core.config.settings import Settings, get_settings
from app.core.logging.logger import get_logger
from app.domain.value_objects.passport_fields import (
    canonical_passport_fields,
)
from app.infrastructure.ai import post_submission_provider_codec as _provider_codec
from app.infrastructure.ai.bounded_vision_http import (
    VisionResponseRejected,
    post_bounded_vision_response,
)
from app.infrastructure.ai.gemini_model_capabilities import thinking_level_for_model
from app.infrastructure.ai.post_submission_contract import _DOCUMENT_CLASSES as _DOCUMENT_CLASSES
from app.infrastructure.ai.post_submission_contract import (
    _DOCUMENT_REASON_CODES as _DOCUMENT_REASON_CODES,
)
from app.infrastructure.ai.post_submission_contract import (
    _DOCUMENT_REVIEW_EXPLANATIONS as _DOCUMENT_REVIEW_EXPLANATIONS,
)
from app.infrastructure.ai.post_submission_contract import (
    _IMAGE_QUALITY_STATUSES as _IMAGE_QUALITY_STATUSES,
)
from app.infrastructure.ai.post_submission_contract import (
    _MAX_OBSERVED_VALUE_CHARACTERS as _MAX_OBSERVED_VALUE_CHARACTERS,
)
from app.infrastructure.ai.post_submission_contract import (
    _MAX_PROVIDER_RESPONSE_BYTES as _MAX_PROVIDER_RESPONSE_BYTES,
)
from app.infrastructure.ai.post_submission_contract import (
    _MAX_PROVIDER_TEXT_CHARACTERS as _MAX_PROVIDER_TEXT_CHARACTERS,
)
from app.infrastructure.ai.post_submission_contract import (
    _MAX_THOUGHT_SIGNATURE_CHARACTERS as _MAX_THOUGHT_SIGNATURE_CHARACTERS,
)
from app.infrastructure.ai.post_submission_contract import _PAGE_TYPES as _PAGE_TYPES
from app.infrastructure.ai.post_submission_contract import _REASON_CODES as _REASON_CODES
from app.infrastructure.ai.post_submission_contract import _RESPONSE_SCHEMA as _RESPONSE_SCHEMA
from app.infrastructure.ai.post_submission_contract import (
    _SYSTEM_INSTRUCTION as _SYSTEM_INSTRUCTION,
)
from app.infrastructure.ai.post_submission_contract import _VERDICTS as _VERDICTS
from app.infrastructure.ai.post_submission_decision_policy import (
    PostSubmissionConfidenceAgent as PostSubmissionConfidenceAgent,
)
from app.infrastructure.ai.post_submission_decision_policy import (
    PostSubmissionDecisionAgent as PostSubmissionDecisionAgent,
)
from app.infrastructure.ai.post_submission_document_policy import (
    PostSubmissionDocumentAgent as PostSubmissionDocumentAgent,
)
from app.infrastructure.ai.post_submission_document_policy import (
    PostSubmissionDocumentAssessment as PostSubmissionDocumentAssessment,
)
from app.infrastructure.ai.post_submission_field_policy import (
    PostSubmissionFieldAgent as PostSubmissionFieldAgent,
)
from app.infrastructure.ai.post_submission_field_policy import (
    _normalize_passport_value as _normalize_passport_value,
)
from app.infrastructure.ai.post_submission_field_policy import _string_value as _string_value
from app.infrastructure.ai.post_submission_result_formatter import (
    PostSubmissionFormatterAgent as PostSubmissionFormatterAgent,
)
from app.infrastructure.ai_priority.metrics import AiPriorityMetrics
from app.infrastructure.ai_priority.provider_metrics import record_provider_event
from app.infrastructure.ai_priority.retry import (
    parse_retry_after_ms,
    retry_after_delay_seconds,
)
from app.infrastructure.ai_priority.state import AiWorkload

logger = get_logger(__name__)


class GeminiPostSubmissionVerificationService(IPostSubmissionPassportVerificationService):
    """Coordinate one Gemini vision request and deterministic typed review stages."""

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        http_client: httpx.AsyncClient | None = None,
        document_agent: PostSubmissionDocumentAgent | None = None,
        field_agent: PostSubmissionFieldAgent | None = None,
        confidence_agent: PostSubmissionConfidenceAgent | None = None,
        decision_agent: PostSubmissionDecisionAgent | None = None,
        formatter_agent: PostSubmissionFormatterAgent | None = None,
        retry_jitter: Callable[[], float] | None = None,
        priority_metrics: AiPriorityMetrics | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._http_client = http_client
        self._document_agent = document_agent or PostSubmissionDocumentAgent()
        self._field_agent = field_agent or PostSubmissionFieldAgent()
        self._confidence_agent = confidence_agent or PostSubmissionConfidenceAgent()
        self._decision_agent = decision_agent or PostSubmissionDecisionAgent()
        self._formatter_agent = formatter_agent or PostSubmissionFormatterAgent()
        self._retry_jitter = retry_jitter or random.random
        self._priority_metrics = (
            priority_metrics if priority_metrics is not None else AiPriorityMetrics()
        )

    async def verify(
        self,
        image_content: bytes,
        *,
        content_type: str,
        submitted_fields: dict[str, Any],
    ) -> PostSubmissionVerificationResult:
        canonical_fields = canonical_passport_fields(submitted_fields) or {}
        submitted_fields = {
            field: canonical_fields[field]
            for field in POST_SUBMISSION_PASSPORT_FIELDS
            if field in canonical_fields
        }
        api_key = self._api_key()
        models = self._model_candidates()
        model = models[0]
        if not self._settings.gemini_verification_enabled:
            return PostSubmissionVerificationResult.fallback(
                provider_status="disabled",
                reason_code="verification_disabled",
                model=model,
                submitted_fields=submitted_fields,
            )
        if not api_key:
            return PostSubmissionVerificationResult.fallback(
                provider_status="not_configured",
                reason_code="api_key_missing",
                model=model,
                submitted_fields=submitted_fields,
            )

        timeout_seconds = self._settings.gemini_timeout_seconds
        payload = self._request_payload(
            image_content,
            content_type=content_type,
            submitted_fields=submitted_fields,
        )
        deadline = time.monotonic() + timeout_seconds
        response: httpx.Response | None = None
        last_transport_status = "network_error"
        last_transport_reason = "provider_network_error"
        max_attempts = min(
            self._settings.gemini_retry_max_attempts,
            self._settings.gemini_max_retries + 1,
        )
        for attempt in range(max_attempts):
            model = models[min(attempt, len(models) - 1)]
            payload["generationConfig"]["thinkingConfig"] = {
                "thinkingLevel": thinking_level_for_model(model)
            }
            endpoint = (
                f"{self._settings.gemini_api_base_url.rstrip('/')}/models/{model}:generateContent"
            )
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                last_transport_status = "timeout"
                last_transport_reason = "provider_timeout"
                break
            attempts_left = max_attempts - attempt
            attempt_timeout = (
                remaining if attempts_left == 1 else max(0.01, remaining / attempts_left)
            )
            timeout = httpx.Timeout(
                attempt_timeout,
                connect=min(2.0, attempt_timeout),
                read=attempt_timeout,
                write=min(3.0, attempt_timeout),
                pool=min(1.0, attempt_timeout),
            )
            attempt_started = time.monotonic()
            logger.info(
                "post_submission_verification_request_attempt",
                attempt=attempt + 1,
                max_attempts=max_attempts,
                model=model,
            )
            try:
                response = await self._post(
                    endpoint,
                    api_key=api_key,
                    payload=payload,
                    timeout=timeout,
                    timeout_seconds=attempt_timeout,
                )
            except VisionResponseRejected:
                await record_provider_event(
                    self._priority_metrics,
                    workload=AiWorkload.VERIFICATION,
                    event="upstream_failure",
                    duration_ms=(time.monotonic() - attempt_started) * 1_000,
                    retry_number=attempt + 1,
                )
                return self._fallback(
                    "invalid_response",
                    "invalid_provider_response",
                    model,
                    submitted_fields,
                )
            except (TimeoutError, httpx.TimeoutException):
                last_transport_status = "timeout"
                last_transport_reason = "provider_timeout"
                response = None
                await record_provider_event(
                    self._priority_metrics,
                    workload=AiWorkload.VERIFICATION,
                    event="timeout",
                    duration_ms=(time.monotonic() - attempt_started) * 1_000,
                    retry_number=attempt + 1,
                )
            except httpx.TransportError as exc:
                logger.warning(
                    "post_submission_verification_transport_retry",
                    error_type=type(exc).__name__,
                    attempt=attempt + 1,
                )
                response = None
                await record_provider_event(
                    self._priority_metrics,
                    workload=AiWorkload.VERIFICATION,
                    event="network_error",
                    duration_ms=(time.monotonic() - attempt_started) * 1_000,
                    retry_number=attempt + 1,
                )

            retry_after_ms = parse_retry_after_ms(
                response.headers.get("Retry-After") if response is not None else None
            )
            logger.info(
                "post_submission_verification_response_metadata",
                attempt=attempt + 1,
                model=model,
                http_status=response.status_code if response is not None else None,
                response_bytes=len(response.content) if response is not None else 0,
                duration_ms=round(
                    (time.monotonic() - attempt_started) * 1000,
                    1,
                ),
                transport_status=("response" if response is not None else last_transport_status),
                retry_after_ms=retry_after_ms,
            )
            if response is not None:
                await record_provider_event(
                    self._priority_metrics,
                    workload=AiWorkload.VERIFICATION,
                    event=(
                        "upstream_429"
                        if response.status_code == 429
                        else ("success" if response.status_code < 400 else "upstream_failure")
                    ),
                    duration_ms=(time.monotonic() - attempt_started) * 1_000,
                    retry_number=attempt + 1,
                )
            remaining = deadline - time.monotonic()
            transient_response = response is not None and (
                response.status_code == 429 or response.status_code >= 500
            )
            if (
                attempt < max_attempts - 1
                and remaining > 0.25
                and (response is None or transient_response)
            ):
                retry_delay = retry_after_delay_seconds(
                    (response.headers.get("Retry-After") if response is not None else None),
                    remaining_seconds=remaining,
                    attempt_number=attempt + 1,
                    jitter_unit=self._retry_jitter(),
                )
                if retry_delay is None:
                    break
                logger.info(
                    "post_submission_verification_retrying",
                    completed_attempt=attempt + 1,
                    next_model=models[min(attempt + 1, len(models) - 1)],
                    retry_after_ms=retry_after_ms,
                    retry_delay_ms=round(retry_delay * 1_000, 2),
                    remaining_ms=round(remaining * 1_000, 2),
                )
                await record_provider_event(
                    self._priority_metrics,
                    workload=AiWorkload.VERIFICATION,
                    event="retry",
                    retry_number=attempt + 1,
                )
                if retry_delay > 0:
                    await asyncio.sleep(retry_delay)
                continue
            break

        if response is None:
            return self._fallback(
                last_transport_status,
                last_transport_reason,
                model,
                submitted_fields,
            )

        provider_failure = self._provider_failure(response.status_code)
        if provider_failure is not None:
            return self._fallback(
                provider_failure[0],
                provider_failure[1],
                model,
                submitted_fields,
            )

        try:
            if len(response.content) > _MAX_PROVIDER_RESPONSE_BYTES:
                raise ValueError("Gemini response exceeded the configured bound")
            provider_json = self._extract_provider_json(response.json())
            document_assessment = self._document_agent.evaluate(provider_json["document"])
            field_results = self._field_agent.evaluate(
                provider_json["fields"],
                submitted_fields,
            )
            calibrated = self._confidence_agent.calibrate(field_results)
            decision = self._decision_agent.decide(calibrated, submitted_fields)
            if document_assessment.requires_review:
                decision = PostSubmissionVerificationDecision.NEEDS_REVIEW
            result = self._formatter_agent.format(
                fields=calibrated,
                decision=decision,
                document_assessment=document_assessment,
                submitted_fields=submitted_fields,
                model=model,
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            return self._fallback(
                "invalid_response",
                "invalid_provider_response",
                model,
                submitted_fields,
            )

        counts = {
            verdict.value: sum(field.verdict == verdict for field in result.fields)
            for verdict in PostSubmissionFieldVerdict
        }
        logger.info(
            "post_submission_verification_completed",
            model=model,
            decision=result.decision.value,
            document_class=document_assessment.document_class,
            page_type=document_assessment.page_type,
            image_quality=document_assessment.image_quality,
            classification_confidence=(document_assessment.classification_confidence),
            reason_code=result.reason_code,
            correct_count=counts["correct"],
            suspicious_count=counts["suspicious"],
            incorrect_count=counts["incorrect"],
        )
        return result

    async def _post(
        self,
        endpoint: str,
        *,
        api_key: str,
        payload: dict[str, Any],
        timeout: httpx.Timeout,
        timeout_seconds: float,
    ) -> httpx.Response:
        headers = {
            "x-goog-api-key": api_key,
            "Content-Type": "application/json",
        }
        async with asyncio.timeout(timeout_seconds):
            if self._http_client is not None:
                return await post_bounded_vision_response(
                    self._http_client,
                    endpoint,
                    headers=headers,
                    payload=payload,
                    timeout=timeout,
                    maximum_bytes=_MAX_PROVIDER_RESPONSE_BYTES,
                )
            async with httpx.AsyncClient(timeout=timeout) as client:
                return await post_bounded_vision_response(
                    client,
                    endpoint,
                    headers=headers,
                    payload=payload,
                    timeout=timeout,
                    maximum_bytes=_MAX_PROVIDER_RESPONSE_BYTES,
                )

    def _request_payload(
        self,
        image_content: bytes,
        *,
        content_type: str,
        submitted_fields: dict[str, Any],
    ) -> dict[str, Any]:
        return _provider_codec._request_payload(
            self, image_content, content_type=content_type, submitted_fields=submitted_fields
        )

    @staticmethod
    def _extract_provider_json(response_payload: dict[str, Any]) -> dict[str, Any]:
        return _provider_codec._extract_provider_json(response_payload)

    @staticmethod
    def _provider_failure(status_code: int) -> tuple[str, str] | None:
        return _provider_codec._provider_failure(status_code)

    @staticmethod
    def _fallback(
        provider_status: str,
        reason_code: str,
        model: str,
        submitted_fields: dict[str, Any],
    ) -> PostSubmissionVerificationResult:
        logger.warning(
            "post_submission_verification_fallback",
            provider_status=provider_status,
            reason_code=reason_code,
        )
        return PostSubmissionVerificationResult.fallback(
            provider_status=provider_status,
            reason_code=reason_code,
            model=model,
            submitted_fields=submitted_fields,
        )

    def _api_key(self) -> str:
        secret = self._settings.google_api_key
        return secret.get_secret_value().strip() if secret else ""

    def _model_candidates(self) -> tuple[str, ...]:
        configured = (
            self._settings.gemini_model,
            self._settings.gemini_fallback_model,
        )
        candidates = tuple(dict.fromkeys(model.strip() for model in configured if model.strip()))
        return candidates or ("gemini-3.5-flash",)

    @staticmethod
    def _safe_content_type(content_type: str) -> str:
        return _provider_codec._safe_content_type(content_type)
