"""Gemini image verification for client-review passport fields."""

from __future__ import annotations

import json
import random
import time
from collections.abc import Callable
from typing import Any

import httpx

from app.application.interfaces.passport_verification import (
    IPassportVerificationService,
    PassportVerificationResult,
)
from app.core.config.settings import Settings, get_settings
from app.core.logging.logger import get_logger
from app.core.time_budget import TimeBudget
from app.infrastructure.ai import passport_extraction_codec as _passport_extraction_codec
from app.infrastructure.ai import passport_extraction_fields as _passport_extraction_fields
from app.infrastructure.ai import passport_extraction_transport as _passport_extraction_transport
from app.infrastructure.ai.passport_extraction_contract import _ACTIONS as _ACTIONS
from app.infrastructure.ai.passport_extraction_contract import (
    _DOCUMENT_CLASSES as _DOCUMENT_CLASSES,
)
from app.infrastructure.ai.passport_extraction_contract import (
    _DOCUMENT_REASON_CODES as _DOCUMENT_REASON_CODES,
)
from app.infrastructure.ai.passport_extraction_contract import _FIELD_CODES as _FIELD_CODES
from app.infrastructure.ai.passport_extraction_contract import (
    _IMAGE_QUALITY_STATUSES as _IMAGE_QUALITY_STATUSES,
)
from app.infrastructure.ai.passport_extraction_contract import (
    _MAX_FIELD_VALUE_CHARS as _MAX_FIELD_VALUE_CHARS,
)
from app.infrastructure.ai.passport_extraction_contract import (
    _MAX_GEMINI_SECONDS as _MAX_GEMINI_SECONDS,
)
from app.infrastructure.ai.passport_extraction_contract import (
    _MAX_PROVIDER_RESPONSE_BYTES as _MAX_PROVIDER_RESPONSE_BYTES,
)
from app.infrastructure.ai.passport_extraction_contract import (
    _MIN_EXTRACTION_OUTPUT_TOKENS as _MIN_EXTRACTION_OUTPUT_TOKENS,
)
from app.infrastructure.ai.passport_extraction_contract import _PAGE_TYPES as _PAGE_TYPES
from app.infrastructure.ai.passport_extraction_contract import _RESPONSE_SCHEMA as _RESPONSE_SCHEMA
from app.infrastructure.ai.passport_extraction_contract import (
    _REVERSE_FIELD_CODES as _REVERSE_FIELD_CODES,
)
from app.infrastructure.ai.passport_extraction_contract import (
    _SYSTEM_INSTRUCTION as _SYSTEM_INSTRUCTION,
)
from app.infrastructure.ai.passport_extraction_contract import PASSPORT_FIELDS as PASSPORT_FIELDS
from app.infrastructure.ai_priority.metrics import AiPriorityMetrics
from app.infrastructure.validation.passport_field_validator import PassportFieldValidator

logger = get_logger(__name__)


class GeminiPassportVerificationService(IPassportVerificationService):
    """Calls Gemini server-side and preserves review fields on provider failure."""

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        http_client: httpx.AsyncClient | None = None,
        retry_jitter: Callable[[], float] | None = None,
        priority_metrics: AiPriorityMetrics | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._http_client = http_client
        self._retry_jitter = retry_jitter or random.random
        self._validator = PassportFieldValidator()
        self._priority_metrics = (
            priority_metrics if priority_metrics is not None else AiPriorityMetrics()
        )

    async def verify(
        self,
        image_content: bytes,
        *,
        content_type: str,
        extracted_fields: dict[str, Any],
        timeout_seconds: float | None = None,
    ) -> PassportVerificationResult:
        started = time.perf_counter()
        original = dict(extracted_fields)
        api_key = self._api_key()
        if not api_key:
            return self._fallback(original, status="not_configured", started=started, attempts=0)

        configured_timeout = min(
            self._settings.gemini_extraction_timeout_ms / 1_000,
            _MAX_GEMINI_SECONDS,
        )
        total_timeout = (
            configured_timeout
            if timeout_seconds is None
            else min(configured_timeout, timeout_seconds)
        )
        if total_timeout <= 0:
            return self._fallback(
                original,
                status="deadline_exhausted",
                started=started,
                attempts=0,
            )
        budget = TimeBudget.start(total_timeout)
        payload = self._request_payload(image_content, content_type, extracted_fields)
        headers = {
            "x-goog-api-key": api_key,
            "Content-Type": "application/json",
        }
        if self._http_client is not None:
            response, failure_status, attempts, provider_model = await self._request_with_retries(
                self._http_client,
                headers=headers,
                payload=payload,
                budget=budget,
                original=original,
            )
        else:
            async with httpx.AsyncClient() as client:
                (
                    response,
                    failure_status,
                    attempts,
                    provider_model,
                ) = await self._request_with_retries(
                    client,
                    headers=headers,
                    payload=payload,
                    budget=budget,
                    original=original,
                )

        if response is None:
            status = failure_status or "provider_unavailable"
            logger.warning(
                "gemini_passport_verification_fallback",
                reason=status,
                attempts=attempts,
                model=provider_model,
            )
            return self._fallback(
                original,
                status=status,
                started=started,
                attempts=attempts,
                model=provider_model,
            )

        try:
            if len(response.content) > _MAX_PROVIDER_RESPONSE_BYTES:
                raise ValueError("Gemini response exceeded the bounded response size")
            provider_result = self._extract_provider_json(response.json())
            classification_status = self._classification_status(provider_result)
            if classification_status is not None:
                metadata = self._metadata(
                    status=classification_status,
                    started=started,
                    provider_status=str(provider_result["s"]),
                    attempts=attempts,
                    model=provider_model,
                    document_class=str(provider_result["d"]),
                    page_type=str(provider_result["p"]),
                    image_quality=str(provider_result["q"]),
                    classification_confidence=float(provider_result["dc"]),
                    reason_code=str(provider_result["r"]),
                )
                merged = dict(original)
                merged["ai_verification"] = metadata
                logger.info(
                    "gemini_passport_document_rejected",
                    status=classification_status,
                    document_class=metadata["document_class"],
                    page_type=metadata["page_type"],
                    reason_code=metadata["reason_code"],
                    model=provider_model,
                    duration_ms=metadata["duration_ms"],
                )
                return PassportVerificationResult(
                    merged_fields=merged,
                    metadata=metadata,
                )
            merged, corrected, filled, absent, field_confidences = self._merge(
                original,
                provider_result,
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            logger.warning(
                "gemini_passport_verification_fallback",
                reason="invalid_response",
                model=provider_model,
            )
            return self._fallback(
                original,
                status="invalid_response",
                started=started,
                attempts=attempts,
                model=provider_model,
            )

        provider_status = str(provider_result["s"])
        accepted_status = (
            "verified"
            if provider_status == "match" and not corrected and not filled and not absent
            else "enhanced"
        )
        metadata = self._metadata(
            status=accepted_status,
            started=started,
            corrected_fields=corrected,
            filled_fields=filled,
            absent_fields=absent,
            field_confidences=field_confidences,
            provider_status=provider_status,
            attempts=attempts,
            model=provider_model,
            document_class=str(provider_result["d"]),
            page_type=str(provider_result["p"]),
            image_quality=str(provider_result["q"]),
            classification_confidence=float(provider_result["dc"]),
            reason_code=str(provider_result["r"]),
        )
        merged["ai_verification"] = metadata
        logger.info(
            "gemini_passport_verification_completed",
            status=accepted_status,
            corrected_count=len(corrected),
            filled_count=len(filled),
            model=provider_model,
            duration_ms=metadata["duration_ms"],
        )
        return PassportVerificationResult(merged_fields=merged, metadata=metadata)

    async def _request_with_retries(
        self,
        client: httpx.AsyncClient,
        *,
        headers: dict[str, str],
        payload: dict[str, Any],
        budget: TimeBudget,
        original: dict[str, Any],
    ) -> tuple[httpx.Response | None, str | None, int, str]:
        return await _passport_extraction_transport._request_with_retries(
            self,
            client,
            headers=headers,
            payload=payload,
            budget=budget,
            original=original,
            logger=logger,
        )

    def _model_route(self) -> tuple[str, ...]:
        return _passport_extraction_transport._model_route(self)

    def _endpoint_for_model(self, model: str) -> str:
        return _passport_extraction_transport._endpoint_for_model(self, model)

    @staticmethod
    def _response_failure(status_code: int) -> tuple[str | None, bool]:
        return _passport_extraction_transport._response_failure(status_code)

    def _successful_response_failure(
        self,
        response: httpx.Response,
        *,
        original: dict[str, Any],
    ) -> str | None:
        return _passport_extraction_codec._successful_response_failure(
            self, response, original=original, logger=logger
        )

    @staticmethod
    def _safe_response_metadata(response: httpx.Response) -> dict[str, str | int]:
        return _passport_extraction_codec._safe_response_metadata(response)

    def _request_payload(
        self,
        image_content: bytes,
        content_type: str,
        extracted_fields: dict[str, Any],
    ) -> dict[str, Any]:
        return _passport_extraction_codec._request_payload(
            self, image_content, content_type, extracted_fields
        )

    @staticmethod
    def _extract_provider_json(response_payload: dict[str, Any]) -> dict[str, Any]:
        return _passport_extraction_codec._extract_provider_json(response_payload)

    @staticmethod
    def _classification_status(provider_result: dict[str, Any]) -> str | None:
        return _passport_extraction_codec._classification_status(provider_result)

    def _merge(
        self,
        original: dict[str, Any],
        provider_result: dict[str, Any],
    ) -> tuple[
        dict[str, Any],
        list[str],
        list[str],
        list[str],
        dict[str, float],
    ]:
        return _passport_extraction_fields._merge(self, original, provider_result)

    def _normalize(self, field: str, raw_value: Any) -> str:
        return _passport_extraction_fields._normalize(self, field, raw_value)

    def _fallback(
        self,
        original: dict[str, Any],
        *,
        status: str,
        started: float,
        attempts: int,
        model: str | None = None,
    ) -> PassportVerificationResult:
        metadata = self._metadata(
            status=status,
            started=started,
            attempts=attempts,
            model=model,
        )
        merged = dict(original)
        merged["ai_verification"] = metadata
        return PassportVerificationResult(merged_fields=merged, metadata=metadata)

    def _metadata(
        self,
        *,
        status: str,
        started: float,
        corrected_fields: list[str] | None = None,
        filled_fields: list[str] | None = None,
        absent_fields: list[str] | None = None,
        field_confidences: dict[str, float] | None = None,
        provider_status: str | None = None,
        attempts: int = 0,
        model: str | None = None,
        document_class: str | None = None,
        page_type: str | None = None,
        image_quality: str | None = None,
        classification_confidence: float | None = None,
        reason_code: str | None = None,
    ) -> dict[str, Any]:
        metadata = {
            "status": status,
            "available": status in {"verified", "enhanced"},
            "model": model or self._settings.gemini_model,
            "provider_status": provider_status,
            "attempts": attempts,
            "corrected_fields": corrected_fields or [],
            "filled_fields": filled_fields or [],
            "absent_fields": absent_fields or [],
            "field_confidences": field_confidences or {},
            "duration_ms": round((time.perf_counter() - started) * 1000, 2),
        }
        if document_class is not None:
            metadata["document_class"] = document_class
            metadata["page_type"] = page_type
            metadata["image_quality"] = image_quality
            metadata["classification_confidence"] = round(
                classification_confidence or 0.0,
                4,
            )
            metadata["reason_code"] = reason_code
        return metadata

    def _api_key(self) -> str:
        secret = self._settings.google_api_key
        return secret.get_secret_value().strip() if secret else ""

    @staticmethod
    def _safe_content_type(content_type: str) -> str:
        return _passport_extraction_codec._safe_content_type(content_type)

    @staticmethod
    def _string_value(value: Any) -> str:
        return _passport_extraction_fields._string_value(value)

    @staticmethod
    def _prompt_value(value: Any) -> str:
        return _passport_extraction_codec._prompt_value(value)
