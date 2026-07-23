"""Guarded Gemini image editing for staff-managed Visa photographs."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import io
import json
import math
import re
import time
from dataclasses import dataclass
from typing import Any

import httpx
from PIL import Image

from app.core.config.settings import Settings, get_settings
from app.core.logging.logger import get_logger
from app.infrastructure.ai.gemini_model_capabilities import thinking_level_for_model
from app.infrastructure.ai_priority.retry import retry_after_delay_seconds
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
        r"\b(change|replace|swap)\b.{0,30}\b(face|identity|person|gender|ethnicity|skin)\b",
        r"\b(make|look)\b.{0,20}\b(younger|older|different person)\b",
        r"\b(add|remove)\b.{0,30}\b(glasses|scar|mole|tattoo|beard|moustache|mustache|hair)\b",
        r"\b(deepfake|face[ -]?swap|impersonat)\b",
    )
)
_SYSTEM_INSTRUCTION = """
You are editing a Visa application portrait. Preserve the exact same person's
identity, facial geometry, age, skin tone, expression, hair, clothing, and all
biometric traits. Only apply presentation-quality corrections requested by the
operator, such as plain white background cleanup, exposure, neutral color,
minor lighting balance, noise reduction, or photographic sharpness. Do not add
or remove people, accessories, facial features, marks, hair, or clothing. Keep
the original framing, pose, dimensions, and aspect ratio. Return one edited
image and no invented content.
""".strip()
_VERIFY_INSTRUCTION = """
Compare the original Visa portrait and edited candidate. Approve only when they
show the same person and the candidate preserves facial geometry, age, skin
tone, expression, hair, clothing, pose, framing, and biometric traits, with no
generated artifacts. Return JSON only.
""".strip()
_VERIFY_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "same_identity": {"type": "BOOLEAN"},
        "presentation_only": {"type": "BOOLEAN"},
        "artifact_free": {"type": "BOOLEAN"},
        "confidence": {"type": "NUMBER"},
    },
    "required": ["same_identity", "presentation_only", "artifact_free", "confidence"],
}


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
        model = self._settings.gemini_image_edit_model.strip()
        api_key = (
            self._settings.google_api_key.get_secret_value()
            if self._settings.google_api_key
            else ""
        )
        if not model or not api_key:
            raise GeminiVisaImageEditNotConfigured(
                "Visa AI editing is not configured. Add GEMINI_IMAGE_EDIT_MODEL and a Google API key."
            )
        if not _MODEL_PATTERN.fullmatch(model):
            raise GeminiVisaImageEditNotConfigured(
                "The configured Visa image model name is invalid."
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
                    generated = await self._generate(
                        model=model,
                        api_key=api_key,
                        image_content=canonical,
                        prompt=normalized_prompt,
                        deadline=deadline,
                    )
                    try:
                        candidate = await asyncio.to_thread(
                            self._canonical_image,
                            generated,
                            self._image_size(canonical),
                        )
                    except PassportImageCropError as exc:
                        raise GeminiVisaImageEditProviderRejected(
                            "Gemini returned an unreadable edited image."
                        ) from exc
                    await self._verify_identity(
                        api_key=api_key,
                        original=canonical,
                        candidate=candidate,
                        deadline=deadline,
                    )
        except TimeoutError as exc:
            raise GeminiVisaImageEditProviderUnavailable(
                "Visa AI image processing timed out. Please try again."
            ) from exc
        logger.info(
            "visa_ai_image_edit_generated",
            model=model,
            prompt_sha256=prompt_hash,
            output_bytes=len(candidate),
        )
        return GeminiVisaImageEditResult(
            content=candidate,
            content_type="image/jpeg",
            prompt_sha256=prompt_hash,
            model=model,
        )

    async def _generate(
        self,
        *,
        model: str,
        api_key: str,
        image_content: bytes,
        prompt: str,
        deadline: float,
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
            stage="generation",
            deadline=deadline,
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

    async def _verify_identity(
        self,
        *,
        api_key: str,
        original: bytes,
        candidate: bytes,
        deadline: float,
    ) -> None:
        payload = {
            "systemInstruction": {"parts": [{"text": _VERIFY_INSTRUCTION}]},
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {"text": "Original image"},
                        {
                            "inlineData": {
                                "mimeType": "image/jpeg",
                                "data": base64.b64encode(original).decode("ascii"),
                            }
                        },
                        {"text": "Edited candidate"},
                        {
                            "inlineData": {
                                "mimeType": "image/jpeg",
                                "data": base64.b64encode(candidate).decode("ascii"),
                            }
                        },
                    ],
                }
            ],
            "generationConfig": {
                "responseMimeType": "application/json",
                "responseSchema": _VERIFY_SCHEMA,
                "maxOutputTokens": 256,
                "thinkingConfig": {
                    "thinkingLevel": thinking_level_for_model(self._settings.gemini_model)
                },
            },
        }
        response = await self._post(
            model=self._settings.gemini_model,
            fallback_model=self._settings.gemini_fallback_model,
            api_key=api_key,
            payload=payload,
            stage="verification",
            deadline=deadline,
        )
        text = next(
            (
                part.get("text")
                for part in self._response_parts(response)
                if isinstance(part.get("text"), str)
            ),
            None,
        )
        try:
            verdict = json.loads(text or "")
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise GeminiVisaImageEditProviderRejected(
                "Gemini identity verification returned an unreadable response."
            ) from exc
        if not isinstance(verdict, dict):
            raise GeminiVisaImageEditProviderRejected(
                "Gemini identity verification returned an unreadable response."
            )
        raw_confidence = verdict.get("confidence")
        if (
            isinstance(raw_confidence, bool)
            or not isinstance(raw_confidence, (int, float))
            or not math.isfinite(float(raw_confidence))
            or not 0.0 <= float(raw_confidence) <= 1.0
        ):
            raise GeminiVisaImageEditProviderRejected(
                "Gemini identity verification returned an invalid confidence score."
            )
        approved = (
            verdict.get("same_identity") is True
            and verdict.get("presentation_only") is True
            and verdict.get("artifact_free") is True
            and float(raw_confidence) >= 0.90
        )
        if not approved:
            raise GeminiVisaImageEditRejected(
                "The generated image could not be verified as an identity-preserving Visa edit. Refine the prompt and try again."
            )

    async def _post(
        self,
        *,
        model: str,
        api_key: str,
        payload: dict[str, Any],
        stage: str,
        deadline: float,
        fallback_model: str | None = None,
    ) -> dict[str, Any]:
        if not _MODEL_PATTERN.fullmatch(model):
            raise GeminiVisaImageEditNotConfigured("The configured Gemini model name is invalid.")
        attempt_limit = min(
            2,
            max(
                1,
                min(
                    self._settings.gemini_retry_max_attempts,
                    self._settings.gemini_max_retries + 1,
                ),
            ),
        )
        normalized_fallback = (fallback_model or "").strip()
        retry_model = (
            normalized_fallback
            if normalized_fallback
            and normalized_fallback != model
            and _MODEL_PATTERN.fullmatch(normalized_fallback)
            else model
        )
        models = [model, retry_model][:attempt_limit]
        last_error: Exception | None = None

        for attempt_index, attempt_model in enumerate(models):
            remaining_seconds = deadline - time.monotonic()
            if remaining_seconds <= 0.05:
                break
            attempts_left = len(models) - attempt_index
            attempt_timeout_seconds = max(0.1, remaining_seconds / attempts_left)
            timeout = httpx.Timeout(
                attempt_timeout_seconds,
                connect=min(5.0, attempt_timeout_seconds),
                write=min(15.0, attempt_timeout_seconds),
                pool=min(5.0, attempt_timeout_seconds),
            )
            endpoint = (
                f"{self._settings.gemini_api_base_url.rstrip('/')}"
                f"/models/{attempt_model}:generateContent"
            )
            request_payload = payload
            if stage == "verification":
                generation_config = dict(payload.get("generationConfig", {}))
                generation_config["thinkingConfig"] = {
                    "thinkingLevel": thinking_level_for_model(attempt_model)
                }
                request_payload = {
                    **payload,
                    "generationConfig": generation_config,
                }
            response: httpx.Response | None = None
            retry_after: str | None = None
            try:
                if self._http_client is not None:
                    response = await self._http_client.post(
                        endpoint,
                        headers={
                            "x-goog-api-key": api_key,
                            "Content-Type": "application/json",
                        },
                        json=request_payload,
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
                            json=request_payload,
                        )
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_error = exc
                logger.warning(
                    "visa_ai_image_edit_provider_unavailable",
                    stage=stage,
                    attempt=attempt_index + 1,
                    model=attempt_model,
                    error_type=type(exc).__name__,
                )
            else:
                if response.status_code < 400:
                    try:
                        payload_json = response.json()
                    except ValueError as exc:
                        raise GeminiVisaImageEditProviderRejected(
                            "Gemini returned an unreadable response. Please try again later."
                        ) from exc
                    if not isinstance(payload_json, dict):
                        raise GeminiVisaImageEditProviderRejected(
                            "Gemini returned an unreadable response. Please try again later."
                        )
                    return payload_json

                if response.status_code != 429 and response.status_code < 500:
                    logger.warning(
                        "visa_ai_image_edit_provider_rejected",
                        stage=stage,
                        status_code=response.status_code,
                        model=attempt_model,
                    )
                    raise GeminiVisaImageEditProviderRejected(
                        "Gemini rejected the Visa photo processing request. "
                        "Check the configured model and try again."
                    )

                retry_after = response.headers.get("Retry-After")
                last_error = httpx.HTTPStatusError(
                    "Gemini provider temporarily unavailable",
                    request=response.request,
                    response=response,
                )
                logger.warning(
                    "visa_ai_image_edit_provider_unavailable",
                    stage=stage,
                    attempt=attempt_index + 1,
                    status_code=response.status_code,
                    model=attempt_model,
                )

            if attempt_index + 1 >= len(models):
                break
            remaining_seconds = deadline - time.monotonic()
            delay_seconds = retry_after_delay_seconds(
                retry_after,
                remaining_seconds=remaining_seconds,
                attempt_number=attempt_index + 1,
            )
            if delay_seconds is None:
                break
            await asyncio.sleep(delay_seconds)

        message = (
            "The Visa photo was generated, but identity verification is temporarily unavailable. "
            "Please try again."
            if stage == "verification"
            else "Gemini image generation is temporarily unavailable. Please try again."
        )
        raise GeminiVisaImageEditProviderUnavailable(message) from last_error

    def _operation_timeout_seconds(self) -> float:
        # Keep lightweight test/alternate settings objects compatible while
        # production Settings supplies the validated configurable value.
        return float(
            getattr(self._settings, "gemini_image_edit_timeout_seconds", 300)
        )

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
                "Visa AI editing cannot change identity, facial traits, age, skin tone, hair, clothing, or accessories."
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
