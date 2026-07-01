"""Gemini final verification for deterministic passport extraction."""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass, field
from typing import Any

from app.core.config.settings import GeminiSettings
from app.core.logging.logger import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class GeminiVerificationResult:
    status: str
    field_results: dict[str, dict[str, Any]] = field(default_factory=dict)
    corrections: dict[str, str] = field(default_factory=dict)
    uncertain_fields: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    raw_response: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "field_results": self.field_results,
            "corrections": self.corrections,
            "uncertain_fields": self.uncertain_fields,
            "notes": self.notes,
        }


class GeminiPassportVerifier:
    """Verifies deterministic fields against the image without doing OCR-first extraction."""

    def __init__(self, settings: GeminiSettings) -> None:
        self._settings = settings

    @property
    def is_available(self) -> bool:
        return bool(self._settings.enabled and self._settings.api_key)

    async def verify(
        self,
        *,
        image_bytes: bytes,
        content_type: str,
        fields: dict[str, str],
        mrz_raw: str | None,
        ocr_output: dict[str, str],
    ) -> GeminiVerificationResult:
        if not self._settings.enabled:
            return GeminiVerificationResult(status="disabled")
        if not self._settings.api_key:
            return GeminiVerificationResult(
                status="skipped",
                notes=["GEMINI_ENABLED is true but GEMINI_API_KEY is not configured."],
            )

        payload = self._build_payload(
            image_bytes=image_bytes,
            content_type=content_type,
            fields=fields,
            mrz_raw=mrz_raw,
            ocr_output=ocr_output,
        )
        url = (
            "https://generativelanguage.googleapis.com/v1beta/"
            f"models/{self._settings.model}:generateContent"
        )
        try:
            import httpx

            async with httpx.AsyncClient(timeout=self._settings.timeout) as client:
                response = await client.post(
                    url,
                    headers={
                        "x-goog-api-key": self._settings.api_key,
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
                response.raise_for_status()
                data = response.json()
        except Exception as exc:
            logger.warning("gemini_passport_verification_failed", error=str(exc))
            return GeminiVerificationResult(
                status="failed",
                notes=["Gemini verification failed; deterministic extraction was kept."],
            )

        parsed = self._parse_response(data)
        return GeminiVerificationResult(
            status="completed",
            field_results=parsed.get("field_results") or {},
            corrections={
                str(key): str(value)
                for key, value in (parsed.get("corrections") or {}).items()
                if isinstance(value, str) and value.strip()
            },
            uncertain_fields=[
                str(value)
                for value in parsed.get("uncertain_fields", [])
                if isinstance(value, str) and value.strip()
            ],
            notes=[
                str(value)
                for value in parsed.get("notes", [])
                if isinstance(value, str) and value.strip()
            ],
            raw_response=data,
        )

    def _build_payload(
        self,
        *,
        image_bytes: bytes,
        content_type: str,
        fields: dict[str, str],
        mrz_raw: str | None,
        ocr_output: dict[str, str],
    ) -> dict[str, Any]:
        prompt = {
            "task": "Verify deterministic passport extraction against the image.",
            "rules": [
                "Do not perform OCR-first extraction.",
                "Do not invent missing values.",
                "Only correct a provided value when the image clearly proves it is wrong.",
                "Return uncertain when the image is unclear or the value cannot be verified.",
            ],
            "deterministic_fields": fields,
            "mrz_output": mrz_raw,
            "targeted_ocr_output": ocr_output,
            "required_json_shape": {
                "field_results": {
                    "field_name": {
                        "status": "confirmed | corrected | uncertain | not_visible",
                        "value": "input value",
                        "corrected_value": "only when clearly wrong",
                        "reason": "short reason",
                    }
                },
                "corrections": {"field_name": "corrected value"},
                "uncertain_fields": ["field_name"],
                "notes": ["short note"],
            },
        }
        return {
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {"text": json.dumps(prompt, sort_keys=True)},
                        {
                            "inlineData": {
                                "mimeType": content_type or "image/jpeg",
                                "data": base64.b64encode(image_bytes).decode("ascii"),
                            }
                        },
                    ],
                }
            ],
            "generationConfig": {
                "temperature": 0,
                "responseMimeType": "application/json",
            },
        }

    def _parse_response(self, data: dict[str, Any]) -> dict[str, Any]:
        text = self._response_text(data)
        if not text:
            return {"notes": ["Gemini response did not contain JSON text."]}
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            cleaned = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```")
            try:
                parsed = json.loads(cleaned.strip())
            except json.JSONDecodeError:
                return {"notes": ["Gemini response was not valid JSON."]}
        return parsed if isinstance(parsed, dict) else {}

    @staticmethod
    def _response_text(data: dict[str, Any]) -> str | None:
        candidates = data.get("candidates")
        if not isinstance(candidates, list) or not candidates:
            return None
        content = candidates[0].get("content") if isinstance(candidates[0], dict) else None
        parts = content.get("parts") if isinstance(content, dict) else None
        if not isinstance(parts, list):
            return None
        texts = [part.get("text") for part in parts if isinstance(part, dict) and isinstance(part.get("text"), str)]
        return "\n".join(texts).strip() or None
