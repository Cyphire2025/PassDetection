"""Passport extraction codec; established service methods delegate here."""

from __future__ import annotations

import base64
import json
from typing import Any, Protocol

import httpx

from app.core.config.settings import Settings
from app.infrastructure.ai.gemini_model_capabilities import thinking_level_for_passport_extraction
from app.infrastructure.ai.passport_extraction_contract import (
    _DOCUMENT_CLASSES,
    _DOCUMENT_REASON_CODES,
    _FIELD_CODES,
    _IMAGE_QUALITY_STATUSES,
    _MAX_FIELD_VALUE_CHARS,
    _MAX_PROVIDER_RESPONSE_BYTES,
    _MIN_EXTRACTION_OUTPUT_TOKENS,
    _PAGE_TYPES,
    _RESPONSE_SCHEMA,
    _REVERSE_FIELD_CODES,
    _SYSTEM_INSTRUCTION,
    PASSPORT_FIELDS,
)


class PassportExtractionCodecContext(Protocol):
    _settings: Settings

    @staticmethod
    def _classification_status(provider_result: dict[str, Any]) -> str | None: ...

    @staticmethod
    def _extract_provider_json(response_payload: dict[str, Any]) -> dict[str, Any]: ...

    def _merge(
        self, original: dict[str, Any], provider_result: dict[str, Any]
    ) -> tuple[dict[str, Any], list[str], list[str], list[str], dict[str, float]]: ...

    @staticmethod
    def _prompt_value(value: Any) -> str: ...

    @staticmethod
    def _safe_content_type(content_type: str) -> str: ...

    @staticmethod
    def _safe_response_metadata(response: httpx.Response) -> dict[str, str | int]: ...

    @staticmethod
    def _string_value(value: Any) -> str: ...


def _successful_response_failure(
    self: PassportExtractionCodecContext,
    response: httpx.Response,
    *,
    original: dict[str, Any],
    logger: Any,
) -> str | None:
    """Reject syntactically successful responses that contain no usable data."""

    validation_stage = "response_size"
    try:
        if len(response.content) > _MAX_PROVIDER_RESPONSE_BYTES:
            raise ValueError("Gemini response exceeded the bounded response size")
        validation_stage = "response_schema"
        provider_result = self._extract_provider_json(response.json())
        validation_stage = "document_classification"
        if self._classification_status(provider_result) is not None:
            # A confident document/quality rejection is a meaningful result,
            # not an extraction-provider failure.
            return None
        validation_stage = "field_values"
        merged, *_ = self._merge(original, provider_result)
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        logger.warning(
            "gemini_passport_verification_invalid_response",
            validation_stage=validation_stage,
            parse_reason=(
                "invalid_json" if isinstance(exc, json.JSONDecodeError) else "invalid_structure"
            ),
            error_type=type(exc).__name__,
            **self._safe_response_metadata(response),
        )
        return "invalid_response"

    if not any(self._string_value(merged.get(field)) for field in PASSPORT_FIELDS):
        return "empty_extraction"
    return None


def _safe_response_metadata(response: httpx.Response) -> dict[str, str | int]:
    """Log only bounded enums/counts, never passport text or thought content."""
    if len(response.content) > _MAX_PROVIDER_RESPONSE_BYTES:
        return {"response_diagnostic": "response_too_large"}
    try:
        payload = response.json()
    except ValueError:
        return {"response_diagnostic": "invalid_json"}
    if not isinstance(payload, dict):
        return {"response_diagnostic": "invalid_envelope"}
    metadata: dict[str, str | int] = {}
    candidates = payload.get("candidates")
    if isinstance(candidates, list) and candidates and isinstance(candidates[0], dict):
        finish = candidates[0].get("finishReason")
        metadata["finish_reason"] = (
            finish
            if isinstance(finish, str)
            and finish
            in {
                "STOP",
                "MAX_TOKENS",
                "SAFETY",
                "RECITATION",
                "OTHER",
                "BLOCKLIST",
                "PROHIBITED_CONTENT",
                "SPII",
                "MALFORMED_FUNCTION_CALL",
            }
            else "missing_or_unknown"
        )
    usage = payload.get("usageMetadata")
    if isinstance(usage, dict):
        for key, name in (
            ("candidatesTokenCount", "output_tokens"),
            ("thoughtsTokenCount", "thinking_tokens"),
            ("totalTokenCount", "total_tokens"),
        ):
            count = usage.get(key)
            if type(count) is int and 0 <= count <= 10_000_000:
                metadata[name] = count
    return metadata


def _request_payload(
    self: PassportExtractionCodecContext,
    image_content: bytes,
    content_type: str,
    extracted_fields: dict[str, Any],
) -> dict[str, Any]:
    compact_fields = {
        _REVERSE_FIELD_CODES[field]: self._prompt_value(extracted_fields.get(field))
        for field in PASSPORT_FIELDS
    }
    compact_input = json.dumps(
        {
            "task": "extract_all_visible_passport_fields_from_image",
            "existing_fields": compact_fields,
        },
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return {
        "systemInstruction": {"parts": [{"text": _SYSTEM_INSTRUCTION}]},
        "contents": [
            {
                "role": "user",
                "parts": [
                    {
                        "inlineData": {
                            "mimeType": self._safe_content_type(content_type),
                            "data": base64.b64encode(image_content).decode("ascii"),
                        }
                    },
                    {"text": compact_input},
                ],
            }
        ],
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseSchema": _RESPONSE_SCHEMA,
            # Gemini includes reasoning in this cap. Legacy deployments
            # configured 512, which can truncate the nine-field result.
            "maxOutputTokens": max(
                _MIN_EXTRACTION_OUTPUT_TOKENS,
                self._settings.gemini_max_output_tokens,
            ),
            "thinkingConfig": {
                "thinkingLevel": thinking_level_for_passport_extraction(self._settings.gemini_model)
            },
        },
    }


def _extract_provider_json(response_payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(response_payload, dict):
        raise ValueError("Unexpected Gemini response root")
    candidates = response_payload["candidates"]
    if not isinstance(candidates, list) or not candidates or not isinstance(candidates[0], dict):
        raise ValueError("Unexpected Gemini candidates")
    if candidates[0].get("finishReason") not in {None, "STOP"}:
        raise ValueError("Gemini response did not finish normally")
    content = candidates[0]["content"]
    if not isinstance(content, dict):
        raise ValueError("Unexpected Gemini content")
    parts = content["parts"]
    if not isinstance(parts, list) or not parts or not isinstance(parts[0], dict):
        raise ValueError("Unexpected Gemini response parts")
    text = parts[0]["text"]
    if not isinstance(text, str) or len(text) > _MAX_PROVIDER_RESPONSE_BYTES:
        raise ValueError("Unexpected Gemini response text")
    parsed = json.loads(text)
    expected_keys = {"d", "p", "q", "dc", "r", "s", "f"}
    if not isinstance(parsed, dict) or set(parsed) != expected_keys:
        raise ValueError("Unexpected Gemini response shape")
    if (
        parsed["d"] not in _DOCUMENT_CLASSES
        or parsed["p"] not in _PAGE_TYPES
        or parsed["q"] not in _IMAGE_QUALITY_STATUSES
        or parsed["r"] not in _DOCUMENT_REASON_CODES
        or isinstance(parsed["dc"], bool)
        or not isinstance(parsed["dc"], (int, float))
        or not 0.0 <= float(parsed["dc"]) <= 1.0
    ):
        raise ValueError("Unexpected Gemini document classification")
    if parsed["s"] not in {"match", "changes", "unreadable"} or not isinstance(parsed["f"], list):
        raise ValueError("Unexpected Gemini verification status")
    if len(parsed["f"]) != len(PASSPORT_FIELDS):
        raise ValueError("Gemini must return every passport field exactly once")
    field_codes = [item.get("k") if isinstance(item, dict) else None for item in parsed["f"]]
    if len(set(field_codes)) != len(PASSPORT_FIELDS) or set(field_codes) != set(_FIELD_CODES):
        raise ValueError("Gemini returned missing, duplicate, or unexpected fields")
    return parsed


def _classification_status(provider_result: dict[str, Any]) -> str | None:
    document_class = str(provider_result["d"])
    page_type = str(provider_result["p"])
    quality = str(provider_result["q"])
    confidence = float(provider_result["dc"])

    if quality == "unreadable":
        return "document_unreadable"
    if quality == "low_quality":
        return "document_low_quality"
    if document_class == "passport_data_page" and page_type == "data_page":
        return None if confidence >= 0.70 else "document_uncertain"
    if document_class == "passport_cover" and confidence >= 0.75:
        return "passport_cover"
    if document_class == "passport_other_page" and confidence >= 0.75:
        return "wrong_passport_page"
    if document_class in {"aadhaar", "pan", "other_document", "not_document"}:
        return "wrong_document" if confidence >= 0.80 else "document_uncertain"
    return "document_uncertain"


def _safe_content_type(content_type: str) -> str:
    normalized = content_type.lower().strip()
    return normalized if normalized in {"image/jpeg", "image/png", "image/webp"} else "image/jpeg"


def _prompt_value(value: Any) -> str:
    return value.strip()[:_MAX_FIELD_VALUE_CHARS] if isinstance(value, str) else ""
