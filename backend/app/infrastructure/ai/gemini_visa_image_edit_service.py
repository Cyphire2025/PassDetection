"""Guarded Gemini image editing for staff-managed Visa photographs."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import io
import re
import time
from dataclasses import dataclass
from typing import Any

import httpx
from PIL import Image

from app.core.config.settings import Settings, get_settings
from app.core.logging.logger import get_logger
from app.infrastructure.imaging.passport_image_cropper import (
    PassportImageCropError,
    render_passport_image_crop,
)

logger = get_logger(__name__)

_MODEL_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_CONTROL_PATTERN = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_DISALLOWED_PROMPT_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\b(change|replace|swap)\b.{0,40}\b(identity|person)\b",
        r"\b(different|another|new)\s+person\b",
        r"\b(deepfake|face[ -]?swap|impersonat)\b",
    )
)
_SYSTEM_INSTRUCTION = """
You are editing a Visa application portrait. Preserve the exact same person's
identity, facial geometry, age, skin tone, and all biometric traits. Apply the
operator's requested presentation edits while keeping the subject recognizably
the same person. Presentation edits may include background cleanup, exposure,
color, lighting, noise reduction, sharpness, crop/framing, and attire styling.
Do not replace the subject, invent a different face, or add another person.
Keep the original dimensions and aspect ratio. Return one edited image.
""".strip()


class GeminiVisaImageEditError(RuntimeError):
    """Safe, user-facing failure for a Visa image edit request."""


class GeminiVisaImageEditNotConfigured(GeminiVisaImageEditError):
    pass


class GeminiVisaImageEditRejected(GeminiVisaImageEditError):
    pass


class GeminiVisaImageEditProviderUnavailable(GeminiVisaImageEditError):
    pass


class GeminiVisaImageEditProviderRejected(GeminiVisaImageEditError):
    pass


class _GeminiVisaImageEditFallbackableProviderRejected(GeminiVisaImageEditProviderRejected):
    """Provider response failure that another configured model may recover from."""


@dataclass(frozen=True, slots=True)
class GeminiVisaImageEditResult:
    content: bytes
    content_type: str
    prompt_sha256: str
    model: str


class GeminiVisaImageEditService:
    _semaphore = asyncio.Semaphore(2)

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._http_client = http_client

    async def edit(self, image_content: bytes, *, prompt: str) -> GeminiVisaImageEditResult:
        normalized_prompt = self.validate_prompt(prompt)
        models = self._configured_models()
        api_key = (
            self._settings.google_api_key.get_secret_value()
            if self._settings.google_api_key
            else ""
        )
        if not models or not api_key:
            raise GeminiVisaImageEditNotConfigured(
                "Visa AI editing is not configured. Add GEMINI_IMAGE_EDIT_MODEL "
                "and a Google API key."
            )

        try:
            canonical = await asyncio.to_thread(self._canonical_image, image_content)
        except PassportImageCropError as exc:
            raise GeminiVisaImageEditError(str(exc)) from exc

        prompt_hash = hashlib.sha256(normalized_prompt.encode("utf-8")).hexdigest()
        operation_timeout_seconds = self._operation_timeout_seconds()
        deadline = time.monotonic() + operation_timeout_seconds
        try:
            async with asyncio.timeout(operation_timeout_seconds):
                async with self._semaphore:
                    for attempt_index, model in enumerate(models, start=1):
                        started_at = time.monotonic()
                        attempts_left = len(models) - attempt_index + 1
                        attempt_timeout_seconds = self._model_attempt_timeout_seconds(
                            deadline=deadline,
                            attempts_left=attempts_left,
                        )
                        try:
                            async with asyncio.timeout(attempt_timeout_seconds):
                                generated = await self._generate(
                                    model=model,
                                    api_key=api_key,
                                    image_content=canonical,
                                    prompt=normalized_prompt,
                                    timeout_seconds=attempt_timeout_seconds,
                                )
                                try:
                                    candidate = await asyncio.to_thread(
                                        self._canonical_image,
                                        generated,
                                        self._image_size(canonical),
                                    )
                                except PassportImageCropError as exc:
                                    raise (
                                        _GeminiVisaImageEditFallbackableProviderRejected(
                                            "Gemini returned an unreadable edited image."
                                        )
                                    ) from exc
                        except TimeoutError as exc:
                            attempt_error: GeminiVisaImageEditError = (
                                GeminiVisaImageEditProviderUnavailable(
                                    "Visa AI image processing timed out. Please try again."
                                )
                            )
                            attempt_error.__cause__ = exc
                        except GeminiVisaImageEditError as exc:
                            attempt_error = exc
                        else:
                            self._log_attempt(
                                model=model,
                                attempt=attempt_index,
                                attempt_count=len(models),
                                outcome="success",
                                started_at=started_at,
                                fallback=False,
                            )
                            logger.info(
                                "visa_ai_image_edit_generated",
                                model=model,
                                attempt=attempt_index,
                                attempt_count=len(models),
                            )
                            return GeminiVisaImageEditResult(
                                content=candidate,
                                content_type="image/jpeg",
                                prompt_sha256=prompt_hash,
                                model=model,
                            )

                        fallback = attempt_index < len(models) and self._is_fallback_eligible(
                            attempt_error
                        )
                        self._log_attempt(
                            model=model,
                            attempt=attempt_index,
                            attempt_count=len(models),
                            outcome=self._attempt_outcome(attempt_error),
                            started_at=started_at,
                            fallback=fallback,
                            error=attempt_error,
                        )
                        if fallback:
                            continue
                        raise attempt_error
        except TimeoutError as exc:
            raise GeminiVisaImageEditProviderUnavailable(
                "Visa AI image processing timed out. Please try again."
            ) from exc

        raise GeminiVisaImageEditProviderUnavailable(
            "Gemini image generation is temporarily unavailable. Please try again."
        )

    async def _generate(
        self,
        *,
        model: str,
        api_key: str,
        image_content: bytes,
        prompt: str,
        timeout_seconds: float,
    ) -> bytes:
        payload = {
            "systemInstruction": {"parts": [{"text": _SYSTEM_INSTRUCTION}]},
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {"text": prompt},
                        {
                            "inlineData": {
                                "mimeType": "image/jpeg",
                                "data": base64.b64encode(image_content).decode("ascii"),
                            }
                        },
                    ],
                }
            ],
            "generationConfig": {"responseModalities": ["TEXT", "IMAGE"]},
        }
        response = await self._post(
            model=model,
            api_key=api_key,
            payload=payload,
            timeout_seconds=timeout_seconds,
        )
        for part in self._response_parts(response):
            inline = part.get("inlineData") or part.get("inline_data")
            if not isinstance(inline, dict):
                continue
            mime_type = str(inline.get("mimeType") or inline.get("mime_type") or "")
            encoded = inline.get("data")
            if mime_type not in {"image/jpeg", "image/png", "image/webp"} or not isinstance(
                encoded, str
            ):
                continue
            try:
                content = base64.b64decode(encoded, validate=True)
            except ValueError as exc:
                raise GeminiVisaImageEditError("Gemini returned an unreadable image.") from exc
            if not content or len(content) > self._settings.upload_max_file_size_bytes:
                raise GeminiVisaImageEditError("Gemini returned an image outside the allowed size.")
            return content
        raise GeminiVisaImageEditError(
            "Gemini did not return an edited image. Try a clearer prompt."
        )

    async def _post(
        self,
        *,
        model: str,
        api_key: str,
        payload: dict[str, Any],
        timeout_seconds: float,
    ) -> dict[str, Any]:
        if not _MODEL_PATTERN.fullmatch(model):
            raise GeminiVisaImageEditNotConfigured("The configured Gemini model name is invalid.")
        timeout = httpx.Timeout(
            timeout_seconds,
            connect=min(5.0, timeout_seconds),
            write=min(15.0, timeout_seconds),
            pool=min(5.0, timeout_seconds),
        )
        endpoint = (
            f"{self._settings.gemini_api_base_url.rstrip('/')}/models/{model}:generateContent"
        )
        try:
            if self._http_client is not None:
                response = await self._http_client.post(
                    endpoint,
                    headers={
                        "x-goog-api-key": api_key,
                        "Content-Type": "application/json",
                    },
                    json=payload,
                    timeout=timeout,
                )
            else:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    response = await client.post(
                        endpoint,
                        headers={
                            "x-goog-api-key": api_key,
                            "Content-Type": "application/json",
                        },
                        json=payload,
                    )
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise GeminiVisaImageEditProviderUnavailable(
                "Gemini image generation is temporarily unavailable. Please try again."
            ) from exc

        if response.status_code < 400:
            try:
                payload_json = response.json()
            except ValueError as exc:
                raise _GeminiVisaImageEditFallbackableProviderRejected(
                    "Gemini returned an unreadable response. Please try again later."
                ) from exc
            if not isinstance(payload_json, dict):
                raise _GeminiVisaImageEditFallbackableProviderRejected(
                    "Gemini returned an unreadable response. Please try again later."
                )
            return payload_json

        status_code = response.status_code
        provider_error = httpx.HTTPStatusError(
            "Gemini provider request failed",
            request=response.request,
            response=response,
        )
        if status_code in {404, 408, 409, 425, 429} or status_code >= 500:
            raise GeminiVisaImageEditProviderUnavailable(
                "Gemini image generation is temporarily unavailable. Please try again."
            ) from provider_error
        if status_code == 400:
            raise _GeminiVisaImageEditFallbackableProviderRejected(
                "Gemini rejected this image-generation request for the selected model."
            ) from provider_error

        raise GeminiVisaImageEditProviderRejected(
            "Gemini rejected the Visa photo processing request. "
            "Check the configured model and try again."
        ) from provider_error

    def _operation_timeout_seconds(self) -> float:
        # Keep lightweight test/alternate settings objects compatible while
        # production Settings supplies the validated configurable value.
        return float(
            getattr(self._settings, "gemini_image_edit_timeout_seconds", 300)
        )

    def _configured_models(self) -> list[str]:
        raw_models = (
            getattr(self._settings, "gemini_image_edit_model", ""),
            getattr(self._settings, "gemini_image_edit_fallback_model", ""),
        )
        models: list[str] = []
        for raw_model in raw_models:
            if not isinstance(raw_model, str):
                raise GeminiVisaImageEditNotConfigured(
                    "The configured Visa image model name is invalid."
                )
            model = raw_model.strip()
            if not model:
                continue
            if not _MODEL_PATTERN.fullmatch(model):
                raise GeminiVisaImageEditNotConfigured(
                    "The configured Visa image model name is invalid."
                )
            if model not in models:
                models.append(model)
        return models

    def _model_attempt_timeout_seconds(
        self,
        *,
        deadline: float,
        attempts_left: int,
    ) -> float:
        remaining_seconds = max(0.05, deadline - time.monotonic())
        fair_share_seconds = remaining_seconds / max(1, attempts_left)
        configured_seconds = float(
            getattr(
                self._settings,
                "gemini_image_edit_attempt_timeout_seconds",
                fair_share_seconds,
            )
        )
        return max(
            0.05,
            min(configured_seconds, fair_share_seconds, remaining_seconds),
        )

    @staticmethod
    def _is_fallback_eligible(error: GeminiVisaImageEditError) -> bool:
        if isinstance(
            error,
            (
                GeminiVisaImageEditNotConfigured,
                GeminiVisaImageEditRejected,
            ),
        ):
            return False
        if isinstance(error, GeminiVisaImageEditProviderRejected):
            return isinstance(
                error,
                _GeminiVisaImageEditFallbackableProviderRejected,
            )
        return True

    @staticmethod
    def _attempt_outcome(error: GeminiVisaImageEditError) -> str:
        cause: BaseException | None = error
        while cause is not None:
            if isinstance(cause, (TimeoutError, httpx.TimeoutException)):
                return "timeout"
            cause = cause.__cause__
        if isinstance(error, GeminiVisaImageEditProviderUnavailable):
            return "provider_unavailable"
        if isinstance(error, _GeminiVisaImageEditFallbackableProviderRejected):
            return "provider_response_unusable"
        if isinstance(error, GeminiVisaImageEditProviderRejected):
            return "provider_rejected"
        return "no_usable_image"

    @staticmethod
    def _provider_status_code(error: GeminiVisaImageEditError) -> int | None:
        cause: BaseException | None = error
        while cause is not None:
            if isinstance(cause, httpx.HTTPStatusError):
                return int(cause.response.status_code)
            cause = cause.__cause__
        return None

    @classmethod
    def _log_attempt(
        cls,
        *,
        model: str,
        attempt: int,
        attempt_count: int,
        outcome: str,
        started_at: float,
        fallback: bool,
        error: GeminiVisaImageEditError | None = None,
    ) -> None:
        fields: dict[str, Any] = {
            "model": model,
            "attempt": attempt,
            "attempt_count": attempt_count,
            "outcome": outcome,
            "fallback": fallback,
            "duration_ms": max(0, round((time.monotonic() - started_at) * 1000)),
        }
        if error is not None:
            fields["error_type"] = type(error).__name__
            status_code = cls._provider_status_code(error)
            if status_code is not None:
                fields["status_code"] = status_code
            logger.warning("visa_ai_image_edit_attempt_completed", **fields)
            return
        logger.info("visa_ai_image_edit_attempt_completed", **fields)

    @staticmethod
    def _response_parts(payload: dict[str, Any]) -> list[dict[str, Any]]:
        candidates = payload.get("candidates")
        if not isinstance(candidates, list) or not candidates:
            raise GeminiVisaImageEditError("Gemini returned no usable result.")
        content = candidates[0].get("content") if isinstance(candidates[0], dict) else None
        parts = content.get("parts") if isinstance(content, dict) else None
        if not isinstance(parts, list):
            raise GeminiVisaImageEditError("Gemini returned no usable result.")
        return [part for part in parts if isinstance(part, dict)]

    @staticmethod
    def validate_prompt(prompt: str) -> str:
        normalized = " ".join(prompt.strip().split())
        if (
            len(normalized) < 3
            or len(normalized) > 1000
            or _CONTROL_PATTERN.search(normalized)
        ):
            raise GeminiVisaImageEditRejected("Enter a valid presentation-edit prompt.")
        if any(pattern.search(normalized) for pattern in _DISALLOWED_PROMPT_PATTERNS):
            raise GeminiVisaImageEditRejected(
                "Visa AI editing cannot replace the person, change identity, "
                "or create a face swap."
            )
        return normalized

    @staticmethod
    def _canonical_image(content: bytes, target_size: tuple[int, int] | None = None) -> bytes:
        rendered = render_passport_image_crop(
            content,
            x=0.0,
            y=0.0,
            width=1.0,
            height=1.0,
            rotation_degrees=0,
            sharpness=1.0,
        )
        if target_size is None or (rendered.output_width, rendered.output_height) == target_size:
            return rendered.content
        with Image.open(io.BytesIO(rendered.content)) as image:
            resized = image.resize(target_size, Image.Resampling.LANCZOS)
            output = io.BytesIO()
            resized.save(output, format="JPEG", quality=93, optimize=True, progressive=True)
            resized.close()
            return output.getvalue()

    @staticmethod
    def _image_size(content: bytes) -> tuple[int, int]:
        with Image.open(io.BytesIO(content)) as image:
            return image.size
