"""Bounded Gemini email transport; request and deterministic result policies have focused owners."""

from __future__ import annotations

import asyncio
import json
import re
import time
from typing import Any, Final
from urllib.parse import quote, urlsplit

import httpx
from pydantic import SecretStr, ValidationError

from app.application.interfaces.email_analysis import IEmailAnalysisService
from app.application.use_cases.email_integrations.action_policy import EmailActionPolicy
from app.core.logging.logger import get_logger
from app.domain.value_objects.email_ai_analysis import (
    ActionDisposition,
    EmailAnalysisProviderStatus,
    EmailAnalysisRequest,
    EmailAnalysisResult,
    GeminiEmailAnalysisPayload,
)
from app.infrastructure.ai.bounded_vision_http import (
    VisionResponseRejected,
    post_bounded_vision_response,
)
from app.infrastructure.ai.gemini_email_codec import (
    _provider_failure,
    _require_visible_aliases,
    parse_email_analysis_response,
)
from app.infrastructure.ai.gemini_email_facts import (
    _canonical_factual_anchor as _canonical_factual_anchor,
)
from app.infrastructure.ai.gemini_email_facts import (
    _factual_anchors as _factual_anchors,
)
from app.infrastructure.ai.gemini_email_facts import (
    _log_unsupported_factual_anchors as _log_unsupported_factual_anchors,
)
from app.infrastructure.ai.gemini_email_payload import _SYSTEM_INSTRUCTION as _SYSTEM_INSTRUCTION
from app.infrastructure.ai.gemini_email_payload import build_email_analysis_payload
from app.infrastructure.ai.gemini_email_result import (
    _has_ambiguous_candidate_links as _has_ambiguous_candidate_links,
)
from app.infrastructure.ai.gemini_email_result import build_email_analysis_result
from app.infrastructure.ai.gemini_email_schema import _response_schema as _response_schema
from app.infrastructure.ai.gemini_email_text import (
    _deadline_is_grounded_in_email as _deadline_is_grounded_in_email,
)
from app.infrastructure.ai.gemini_email_text import (
    _minimize_text as _minimize_text,
)
from app.infrastructure.ai.gemini_email_text import (
    _normalize_visible_phrase as _normalize_visible_phrase,
)
from app.infrastructure.ai.gemini_email_text import (
    _trusted_fact_corpus as _trusted_fact_corpus,
)
from app.infrastructure.ai.gemini_email_text import (
    _ungrounded_deadline as _ungrounded_deadline,
)

logger = get_logger(__name__)

_GEMINI_API_BASE_URL: Final[str] = "https://generativelanguage.googleapis.com/v1beta"
_MAX_PROVIDER_RESPONSE_BYTES: Final[int] = 192 * 1024
_MAX_PROVIDER_TEXT_CHARACTERS: Final[int] = 96 * 1024
_MAX_THOUGHT_SIGNATURE_CHARACTERS: Final[int] = 64 * 1024
_MODEL_NAME_PATTERN: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9._-]{1,128}$")


class GeminiEmailAnalysisService(IEmailAnalysisService):
    """Analyze one bounded email with a caller-supplied Gemini configuration."""

    def __init__(
        self,
        *,
        api_key: SecretStr | str | None,
        model: str,
        timeout_seconds: float,
        api_base_url: str = _GEMINI_API_BASE_URL,
        max_output_tokens: int = 2_048,
        review_confidence_threshold: float = 0.9,
        deadline_confidence_threshold: float = 0.85,
        http_client: httpx.AsyncClient | None = None,
        repair_invalid_response: bool = True,
        action_policy: EmailActionPolicy | None = None,
    ) -> None:
        normalized_model = model.strip()
        if _MODEL_NAME_PATTERN.fullmatch(normalized_model) is None:
            raise ValueError("Gemini model must be a bounded model name")
        if not 0.1 <= timeout_seconds <= 120.0:
            raise ValueError("Gemini timeout must be between 0.1 and 120 seconds")
        normalized_api_base_url = _validated_api_base_url(api_base_url)
        if not 256 <= max_output_tokens <= 8_192:
            raise ValueError("Gemini max output tokens must be between 256 and 8192")
        if not 0.0 <= review_confidence_threshold <= 1.0:
            raise ValueError("Review confidence threshold must be between 0 and 1")
        if not 0.0 <= deadline_confidence_threshold <= 1.0:
            raise ValueError("Deadline confidence threshold must be between 0 and 1")
        self._api_key = (
            api_key.get_secret_value().strip()
            if isinstance(api_key, SecretStr)
            else (api_key or "").strip()
        )
        self._model = normalized_model
        self._timeout_seconds = timeout_seconds
        self._api_base_url = normalized_api_base_url
        self._max_output_tokens = max_output_tokens
        self._review_confidence_threshold = review_confidence_threshold
        self._deadline_confidence_threshold = deadline_confidence_threshold
        self._http_client = http_client
        self._repair_invalid_response = repair_invalid_response
        self._action_policy = action_policy or EmailActionPolicy()

    async def analyze(self, request: EmailAnalysisRequest) -> EmailAnalysisResult:
        if not self._api_key:
            return EmailAnalysisResult.review_fallback(
                provider_status=EmailAnalysisProviderStatus.NOT_CONFIGURED,
                reason_code="api_key_missing",
                model=self._model,
            )

        endpoint = f"{self._api_base_url}/models/{quote(self._model, safe='-._')}:generateContent"
        attempts = 2 if self._repair_invalid_response else 1
        repair_attempted = False
        for attempt in range(attempts):
            is_repair = attempt == 1
            repair_attempted = repair_attempted or is_repair
            payload = self._request_payload(request, repair=is_repair)
            started_at = time.monotonic()
            try:
                response = await self._post(endpoint, payload)
            except VisionResponseRejected:
                if not is_repair and self._repair_invalid_response:
                    logger.info("email_ai_analysis_schema_repair", model=self._model)
                    continue
                return EmailAnalysisResult.review_fallback(
                    provider_status=EmailAnalysisProviderStatus.INVALID_RESPONSE,
                    reason_code="invalid_provider_response",
                    model=self._model,
                    repair_attempted=repair_attempted,
                )
            except (TimeoutError, httpx.TimeoutException):
                logger.warning(
                    "email_ai_analysis_provider_failure",
                    model=self._model,
                    failure="timeout",
                    repair_attempt=is_repair,
                )
                return EmailAnalysisResult.review_fallback(
                    provider_status=EmailAnalysisProviderStatus.TIMEOUT,
                    reason_code="provider_timeout",
                    model=self._model,
                    repair_attempted=repair_attempted,
                )
            except httpx.TransportError as exc:
                logger.warning(
                    "email_ai_analysis_provider_failure",
                    model=self._model,
                    failure="transport",
                    error_type=type(exc).__name__,
                    repair_attempt=is_repair,
                )
                return EmailAnalysisResult.review_fallback(
                    provider_status=EmailAnalysisProviderStatus.PROVIDER_UNAVAILABLE,
                    reason_code="provider_transport_error",
                    model=self._model,
                    repair_attempted=repair_attempted,
                )

            logger.info(
                "email_ai_analysis_response_metadata",
                model=self._model,
                http_status=response.status_code,
                response_bytes=len(response.content),
                duration_ms=round((time.monotonic() - started_at) * 1_000, 1),
                repair_attempt=is_repair,
            )
            provider_failure = self._provider_failure(response.status_code)
            if provider_failure is not None:
                return EmailAnalysisResult.review_fallback(
                    provider_status=provider_failure[0],
                    reason_code=provider_failure[1],
                    model=self._model,
                    repair_attempted=repair_attempted,
                )

            try:
                provider_result = self._parse_response(response)
                self._require_visible_aliases(provider_result, request)
            except (json.JSONDecodeError, TypeError, ValueError, ValidationError):
                if not is_repair and self._repair_invalid_response:
                    logger.info(
                        "email_ai_analysis_schema_repair",
                        model=self._model,
                    )
                    continue
                return EmailAnalysisResult.review_fallback(
                    provider_status=EmailAnalysisProviderStatus.INVALID_RESPONSE,
                    reason_code="invalid_provider_response",
                    model=self._model,
                    repair_attempted=repair_attempted,
                )

            result = self._build_result(provider_result, request, repair_attempted=is_repair)
            logger.info(
                "email_ai_analysis_completed",
                model=self._model,
                relevance=result.relevance.value,
                intent=result.intent.value,
                priority=result.priority.value,
                candidate_count=len(result.candidate_links),
                deadline_count=len(result.deadlines),
                proposal_count=len(result.action_decisions),
                blocked_proposal_count=sum(
                    decision.disposition == ActionDisposition.BLOCKED
                    for decision in result.action_decisions
                ),
                needs_review=result.needs_review,
                repair_attempt=is_repair,
            )
            return result

        return EmailAnalysisResult.review_fallback(
            provider_status=EmailAnalysisProviderStatus.INVALID_RESPONSE,
            reason_code="invalid_provider_response",
            model=self._model,
            repair_attempted=repair_attempted,
        )

    async def _post(
        self,
        endpoint: str,
        payload: dict[str, Any],
    ) -> httpx.Response:
        timeout = httpx.Timeout(
            self._timeout_seconds,
            connect=min(2.0, self._timeout_seconds),
            read=self._timeout_seconds,
            write=min(3.0, self._timeout_seconds),
            pool=min(1.0, self._timeout_seconds),
        )
        headers = {
            "x-goog-api-key": self._api_key,
            "Content-Type": "application/json",
        }
        async with asyncio.timeout(self._timeout_seconds):
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

    def _request_payload(self, request: EmailAnalysisRequest, *, repair: bool) -> dict[str, Any]:
        return build_email_analysis_payload(
            request, repair=repair, max_output_tokens=self._max_output_tokens
        )

    @staticmethod
    def _parse_response(response: httpx.Response) -> GeminiEmailAnalysisPayload:
        return parse_email_analysis_response(
            response,
            maximum_response_bytes=_MAX_PROVIDER_RESPONSE_BYTES,
            maximum_text_characters=_MAX_PROVIDER_TEXT_CHARACTERS,
            maximum_thought_signature_characters=_MAX_THOUGHT_SIGNATURE_CHARACTERS,
        )

    _require_visible_aliases = staticmethod(_require_visible_aliases)
    _provider_failure = staticmethod(_provider_failure)

    def _build_result(
        self,
        provider_result: GeminiEmailAnalysisPayload,
        request: EmailAnalysisRequest,
        *,
        repair_attempted: bool,
    ) -> EmailAnalysisResult:
        return build_email_analysis_result(
            provider_result,
            request,
            repair_attempted=repair_attempted,
            model=self._model,
            review_confidence_threshold=self._review_confidence_threshold,
            deadline_confidence_threshold=self._deadline_confidence_threshold,
            action_policy=self._action_policy,
        )


def _validated_api_base_url(value: str) -> str:
    normalized = value.strip().rstrip("/")
    if not normalized or len(normalized) > 2_048:
        raise ValueError("Gemini API base URL must be a bounded HTTPS URL")
    parsed = urlsplit(normalized)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("Gemini API base URL must be a bounded HTTPS URL")
    return normalized
