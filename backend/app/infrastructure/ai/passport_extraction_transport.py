"""Passport extraction transport; established service methods delegate here."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from typing import Any, Protocol

import httpx

from app.core.config.settings import Settings
from app.core.time_budget import TimeBudget
from app.infrastructure.ai.bounded_vision_http import (
    VisionResponseRejected,
    post_bounded_vision_response,
)
from app.infrastructure.ai.gemini_model_capabilities import thinking_level_for_passport_extraction
from app.infrastructure.ai.passport_extraction_contract import (
    _MAX_PROVIDER_RESPONSE_BYTES,
)
from app.infrastructure.ai_priority.metrics import AiPriorityMetrics
from app.infrastructure.ai_priority.provider_metrics import record_provider_event
from app.infrastructure.ai_priority.retry import parse_retry_after_ms, retry_after_delay_seconds
from app.infrastructure.ai_priority.state import AiWorkload


class PassportExtractionTransportContext(Protocol):
    _priority_metrics: AiPriorityMetrics
    _retry_jitter: Callable[[], float]
    _settings: Settings

    def _endpoint_for_model(self, model: str) -> str: ...

    def _model_route(self) -> tuple[str, ...]: ...

    @staticmethod
    def _response_failure(status_code: int) -> tuple[str | None, bool]: ...

    @staticmethod
    def _safe_response_metadata(response: httpx.Response) -> dict[str, str | int]: ...

    def _successful_response_failure(
        self, response: httpx.Response, *, original: dict[str, Any]
    ) -> str | None: ...


async def _request_with_retries(
    self: PassportExtractionTransportContext,
    client: httpx.AsyncClient,
    *,
    headers: dict[str, str],
    payload: dict[str, Any],
    budget: TimeBudget,
    original: dict[str, Any],
    logger: Any,
) -> tuple[httpx.Response | None, str | None, int, str]:
    model_route = self._model_route()
    attempts = 0
    last_status: str | None = "deadline_exhausted"
    last_model = model_route[0]

    for attempt, model in enumerate(model_route, start=1):
        remaining = budget.remaining()
        if remaining <= 0.01:
            break
        attempts = attempt
        last_model = model
        attempts_left = len(model_route) - attempt + 1
        attempt_timeout = remaining if attempts_left == 1 else max(0.01, remaining / attempts_left)
        attempt_started = time.perf_counter()
        timeout = httpx.Timeout(
            attempt_timeout,
            connect=min(2.0, attempt_timeout),
            read=attempt_timeout,
            write=min(3.0, attempt_timeout),
            pool=min(1.0, attempt_timeout),
        )
        endpoint = self._endpoint_for_model(model)
        transient = False
        semantic_failure = False
        retry_after_ms: int | None = None
        logger.info(
            "gemini_passport_verification_request_started",
            model=model,
            attempt=attempt,
            timeout_ms=round(attempt_timeout * 1000, 2),
        )
        payload["generationConfig"]["thinkingConfig"] = {
            "thinkingLevel": thinking_level_for_passport_extraction(model)
        }
        try:
            async with asyncio.timeout(attempt_timeout):
                response = await post_bounded_vision_response(
                    client,
                    endpoint,
                    headers=headers,
                    payload=payload,
                    timeout=timeout,
                    maximum_bytes=_MAX_PROVIDER_RESPONSE_BYTES,
                )
        except VisionResponseRejected:
            last_status = "invalid_response"
            transient = True
            semantic_failure = True
            response = None
            await record_provider_event(
                self._priority_metrics,
                workload=AiWorkload.EXTRACTION,
                event="upstream_failure",
                duration_ms=(time.perf_counter() - attempt_started) * 1_000,
                retry_number=attempt,
            )
        except (TimeoutError, httpx.TimeoutException):
            last_status = "timeout"
            transient = True
            response = None
            logger.warning(
                "gemini_passport_verification_response_received",
                model=model,
                attempt=attempt,
                provider_status=last_status,
                duration_ms=round(
                    (time.perf_counter() - attempt_started) * 1000,
                    2,
                ),
            )
            await record_provider_event(
                self._priority_metrics,
                workload=AiWorkload.EXTRACTION,
                event="timeout",
                duration_ms=(time.perf_counter() - attempt_started) * 1_000,
                retry_number=attempt,
            )
        except httpx.TransportError:
            last_status = "network_error"
            transient = True
            response = None
            logger.warning(
                "gemini_passport_verification_response_received",
                model=model,
                attempt=attempt,
                provider_status=last_status,
                duration_ms=round(
                    (time.perf_counter() - attempt_started) * 1000,
                    2,
                ),
            )
            await record_provider_event(
                self._priority_metrics,
                workload=AiWorkload.EXTRACTION,
                event="network_error",
                duration_ms=(time.perf_counter() - attempt_started) * 1_000,
                retry_number=attempt,
            )
        except httpx.HTTPError:
            # Configuration/request-construction failures are not made
            # healthier by switching models.
            logger.warning(
                "gemini_passport_verification_response_received",
                model=model,
                attempt=attempt,
                provider_status="provider_request_error",
                duration_ms=round(
                    (time.perf_counter() - attempt_started) * 1000,
                    2,
                ),
            )
            await record_provider_event(
                self._priority_metrics,
                workload=AiWorkload.EXTRACTION,
                event="provider_request_error",
                duration_ms=(time.perf_counter() - attempt_started) * 1_000,
                retry_number=attempt,
            )
            return None, "provider_request_error", attempts, last_model
        else:
            assert response is not None
            retry_after_ms = parse_retry_after_ms(response.headers.get("Retry-After"))
            logger.info(
                "gemini_passport_verification_response_received",
                model=model,
                attempt=attempt,
                http_status=response.status_code,
                response_bytes=len(response.content),
                duration_ms=round(
                    (time.perf_counter() - attempt_started) * 1000,
                    2,
                ),
                retry_after_ms=retry_after_ms,
                **self._safe_response_metadata(response),
            )
            last_status, transient = self._response_failure(response.status_code)
            if last_status is None:
                last_status = self._successful_response_failure(
                    response,
                    original=original,
                )
                if last_status is not None:
                    transient = True
                    semantic_failure = True
                    logger.warning(
                        "gemini_passport_verification_semantic_failure",
                        model=model,
                        attempt=attempt,
                        provider_status=last_status,
                    )
            provider_event = (
                "upstream_429"
                if response.status_code == 429
                else ("success" if last_status is None else "upstream_failure")
            )
            await record_provider_event(
                self._priority_metrics,
                workload=AiWorkload.EXTRACTION,
                event=provider_event,
                duration_ms=(time.perf_counter() - attempt_started) * 1_000,
                retry_number=attempt,
            )
            if last_status is None:
                return response, None, attempts, model

        if not transient or attempt >= len(model_route) or not budget.has_time(0.01):
            return None, last_status, attempts, last_model
        next_model = model_route[attempt]
        # A different model is the recovery path, so switch immediately.
        # Backoff is useful only when retrying the same provider model.
        retry_delay = (
            0.0
            if semantic_failure or next_model != model
            else retry_after_delay_seconds(
                response.headers.get("Retry-After") if response is not None else None,
                remaining_seconds=budget.remaining(),
                attempt_number=attempt,
                jitter_unit=self._retry_jitter(),
            )
        )
        if retry_delay is None:
            return None, last_status, attempts, last_model
        logger.info(
            "gemini_passport_verification_retrying",
            reason=last_status,
            completed_attempt=attempt,
            next_model=next_model,
            remaining_ms=round(budget.remaining() * 1000, 2),
            retry_after_ms=retry_after_ms,
            retry_delay_ms=round(retry_delay * 1_000, 2),
        )
        await record_provider_event(
            self._priority_metrics,
            workload=AiWorkload.EXTRACTION,
            event="retry",
            retry_number=attempt,
        )
        if retry_delay > 0:
            await asyncio.sleep(retry_delay)

    return None, last_status, attempts, last_model


def _model_route(self: PassportExtractionTransportContext) -> tuple[str, ...]:
    primary = self._settings.gemini_model.strip()
    fallback = self._settings.gemini_fallback_model.strip() or primary
    max_attempts = min(
        self._settings.gemini_retry_max_attempts,
        self._settings.gemini_max_retries + 1,
    )
    return (primary, *([fallback] * (max_attempts - 1)))


def _endpoint_for_model(self: PassportExtractionTransportContext, model: str) -> str:
    return f"{self._settings.gemini_api_base_url.rstrip('/')}/models/{model}:generateContent"


def _response_failure(status_code: int) -> tuple[str | None, bool]:
    if status_code == 429:
        return "rate_limited", True
    if status_code >= 500:
        return "provider_unavailable", True
    if status_code in {401, 403}:
        return "permission_denied", False
    if status_code >= 400:
        return "provider_rejected_request", True
    return None, False
