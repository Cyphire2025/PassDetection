"""Bounded provider payload and response codec for post-submit verification."""

from __future__ import annotations

import base64
import json
from typing import Any, Protocol

from app.application.interfaces.post_submission_verification import (
    POST_SUBMISSION_PASSPORT_FIELDS,
)
from app.core.config.settings import Settings
from app.infrastructure.ai.gemini_model_capabilities import thinking_level_for_model
from app.infrastructure.ai.post_submission_contract import (
    _MAX_OBSERVED_VALUE_CHARACTERS,
    _MAX_PROVIDER_TEXT_CHARACTERS,
    _MAX_THOUGHT_SIGNATURE_CHARACTERS,
    _RESPONSE_SCHEMA,
    _SYSTEM_INSTRUCTION,
)
from app.infrastructure.ai.post_submission_field_policy import (
    _string_value,
)


class PostSubmissionCodecContext(Protocol):
    _settings: Settings

    @staticmethod
    def _safe_content_type(content_type: str) -> str: ...


def _request_payload(
    self: PostSubmissionCodecContext,
    image_content: bytes,
    *,
    content_type: str,
    submitted_fields: dict[str, Any],
) -> dict[str, Any]:
    compact_fields = {
        field: _string_value(submitted_fields.get(field))[:_MAX_OBSERVED_VALUE_CHARACTERS]
        for field in POST_SUBMISSION_PASSPORT_FIELDS
    }
    return {
        "systemInstruction": {"parts": [{"text": _SYSTEM_INSTRUCTION}]},
        "contents": [
            {
                "role": "user",
                "parts": [
                    {
                        "text": json.dumps(
                            {"submitted_fields": compact_fields},
                            separators=(",", ":"),
                            ensure_ascii=False,
                        )
                    },
                    {
                        "inlineData": {
                            "mimeType": self._safe_content_type(content_type),
                            "data": base64.b64encode(image_content).decode("ascii"),
                        }
                    },
                ],
            }
        ],
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseSchema": _RESPONSE_SCHEMA,
            "maxOutputTokens": max(1024, self._settings.gemini_max_output_tokens),
            "thinkingConfig": {
                "thinkingLevel": thinking_level_for_model(self._settings.gemini_model)
            },
        },
    }


def _extract_provider_json(response_payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(response_payload, dict):
        raise ValueError("Gemini response must be an object")
    candidates = response_payload.get("candidates")
    if not isinstance(candidates, list) or len(candidates) != 1:
        raise ValueError("Gemini response must contain one candidate")
    candidate = candidates[0]
    if not isinstance(candidate, dict):
        raise ValueError("Gemini candidate must be an object")
    if candidate.get("finishReason") not in {None, "STOP"}:
        raise ValueError("Gemini response did not finish normally")
    content = candidate.get("content")
    if not isinstance(content, dict):
        raise ValueError("Gemini content must be an object")
    parts = content.get("parts")
    if not isinstance(parts, list) or len(parts) != 1:
        raise ValueError("Gemini response must contain one text part")
    part = parts[0]
    if not isinstance(part, dict) or not set(part).issubset({"text", "thoughtSignature"}):
        raise ValueError("Gemini response part contains unexpected data")
    if "text" not in part:
        raise ValueError("Gemini response part must contain text")
    thought_signature = part.get("thoughtSignature")
    if thought_signature is not None and (
        not isinstance(thought_signature, str)
        or len(thought_signature) > _MAX_THOUGHT_SIGNATURE_CHARACTERS
    ):
        raise ValueError("Gemini thought signature must be a bounded string")
    text = part["text"]
    if not isinstance(text, str) or len(text) > _MAX_PROVIDER_TEXT_CHARACTERS:
        raise ValueError("Gemini response text must be a bounded string")
    parsed = json.loads(text)
    if not isinstance(parsed, dict) or set(parsed) != {
        "document",
        "fields",
    }:
        raise ValueError("Unexpected Gemini post-submission response")
    return parsed


def _provider_failure(status_code: int) -> tuple[str, str] | None:
    if status_code == 429:
        return "rate_limited", "provider_rate_limited"
    if status_code >= 500:
        return "provider_unavailable", "provider_unavailable"
    if status_code in {401, 403}:
        return "permission_denied", "provider_permission_denied"
    if status_code >= 400:
        return "request_rejected", "provider_rejected_request"
    return None


def _safe_content_type(content_type: str) -> str:
    normalized = content_type.lower().strip()
    return normalized if normalized in {"image/jpeg", "image/png", "image/webp"} else "image/jpeg"
