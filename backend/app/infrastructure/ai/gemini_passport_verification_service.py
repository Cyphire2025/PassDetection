"""Gemini image verification for client-review passport fields."""

from __future__ import annotations

import asyncio
import base64
import json
import re
import time
from datetime import date, datetime
from typing import Any, Final

import httpx

from app.application.interfaces.passport_verification import (
    IPassportVerificationService,
    PassportVerificationResult,
)
from app.core.config.settings import Settings, get_settings
from app.core.logging.logger import get_logger
from app.domain.value_objects.passport_fields import normalize_extracted_passport_dates
from app.infrastructure.validation.passport_field_validator import PassportFieldValidator

logger = get_logger(__name__)

PASSPORT_FIELDS: Final[tuple[str, ...]] = (
    "surname",
    "given_names",
    "passport_number",
    "nationality",
    "issuing_country",
    "date_of_birth",
    "date_of_issue",
    "date_of_expiry",
    "sex",
)

_FIELD_CODES: Final[dict[str, str]] = {
    "sn": "surname",
    "gn": "given_names",
    "pn": "passport_number",
    "na": "nationality",
    "ic": "issuing_country",
    "db": "date_of_birth",
    "di": "date_of_issue",
    "de": "date_of_expiry",
    "sx": "sex",
}
_REVERSE_FIELD_CODES: Final[dict[str, str]] = {value: key for key, value in _FIELD_CODES.items()}
_ACTIONS: Final[set[str]] = {"keep", "replace", "fill", "unknown"}

_RESPONSE_SCHEMA: Final[dict[str, Any]] = {
    "type": "OBJECT",
    "properties": {
        "s": {"type": "STRING", "enum": ["match", "changes", "unreadable"]},
        "f": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "k": {"type": "STRING", "enum": list(_FIELD_CODES)},
                    "v": {"type": "STRING"},
                    "a": {"type": "STRING", "enum": sorted(_ACTIONS)},
                    "c": {"type": "NUMBER"},
                },
                "required": ["k", "v", "a", "c"],
            },
        },
    },
    "required": ["s", "f"],
}

_SYSTEM_INSTRUCTION: Final[str] = (
    "Verify the passport data-page image against the compact OCR JSON. Return only the schema. "
    "Read exactly these codes: sn surname, gn given names, pn passport number, na nationality "
    "ISO-3, ic issuing country ISO-3, db birth YYYY-MM-DD, di issue YYYY-MM-DD, "
    "de expiry YYYY-MM-DD, sx M/F/X. "
    "For every readable field return keep, replace, or fill; use unknown with empty v when unreadable. "
    "Never infer a value that is not visibly printed. Set confidence c from 0 to 1."
)


class GeminiPassportVerificationService(IPassportVerificationService):
    """Calls Gemini server-side and falls back to the OCR payload on every provider failure."""

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._http_client = http_client
        self._validator = PassportFieldValidator()

    async def verify(
        self,
        image_content: bytes,
        *,
        content_type: str,
        extracted_fields: dict[str, Any],
    ) -> PassportVerificationResult:
        started = time.perf_counter()
        original = dict(extracted_fields)
        api_key = self._api_key()
        if not self._settings.gemini_verification_enabled:
            return self._fallback(original, status="disabled", started=started)
        if not api_key:
            return self._fallback(original, status="not_configured", started=started)

        payload = self._request_payload(image_content, content_type, extracted_fields)
        endpoint = (
            f"{self._settings.gemini_api_base_url.rstrip('/')}"
            f"/models/{self._settings.gemini_model}:generateContent"
        )
        timeout_seconds = self._settings.gemini_timeout_seconds
        timeout = httpx.Timeout(
            timeout_seconds,
            connect=min(2.0, timeout_seconds),
            read=timeout_seconds,
            write=min(3.0, timeout_seconds),
            pool=min(1.0, timeout_seconds),
        )

        try:
            async with asyncio.timeout(timeout_seconds):
                if self._http_client is not None:
                    response = await self._http_client.post(
                        endpoint,
                        headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
                        json=payload,
                        timeout=timeout,
                    )
                else:
                    async with httpx.AsyncClient(timeout=timeout) as client:
                        response = await client.post(
                            endpoint,
                            headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
                            json=payload,
                        )
        except (TimeoutError, httpx.TimeoutException):
            logger.warning("gemini_passport_verification_fallback", reason="timeout")
            return self._fallback(original, status="timeout", started=started)
        except httpx.HTTPError as exc:
            logger.warning(
                "gemini_passport_verification_fallback",
                reason="network_error",
                error_type=type(exc).__name__,
            )
            return self._fallback(original, status="network_error", started=started)

        if response.status_code == 429:
            logger.warning("gemini_passport_verification_fallback", reason="rate_limited")
            return self._fallback(original, status="rate_limited", started=started)
        if response.status_code >= 500:
            logger.warning(
                "gemini_passport_verification_fallback",
                reason="provider_unavailable",
                provider_status=response.status_code,
            )
            return self._fallback(original, status="provider_unavailable", started=started)
        if response.status_code in {401, 403}:
            logger.warning(
                "gemini_passport_verification_fallback",
                reason="permission_denied",
                provider_status=response.status_code,
            )
            return self._fallback(original, status="permission_denied", started=started)
        if response.status_code >= 400:
            logger.warning(
                "gemini_passport_verification_fallback",
                reason="provider_rejected_request",
                provider_status=response.status_code,
            )
            return self._fallback(original, status="provider_rejected_request", started=started)

        try:
            provider_result = self._extract_provider_json(response.json())
            merged, corrected, filled = self._merge(original, provider_result)
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            logger.warning("gemini_passport_verification_fallback", reason="invalid_response")
            return self._fallback(original, status="invalid_response", started=started)

        provider_status = str(provider_result["s"])
        accepted_status = "verified" if provider_status == "match" and not corrected and not filled else "enhanced"
        metadata = self._metadata(
            status=accepted_status,
            started=started,
            corrected_fields=corrected,
            filled_fields=filled,
            provider_status=provider_status,
        )
        merged["ai_verification"] = metadata
        logger.info(
            "gemini_passport_verification_completed",
            status=accepted_status,
            corrected_count=len(corrected),
            filled_count=len(filled),
            duration_ms=metadata["duration_ms"],
        )
        return PassportVerificationResult(merged_fields=merged, metadata=metadata)

    def _request_payload(
        self,
        image_content: bytes,
        content_type: str,
        extracted_fields: dict[str, Any],
    ) -> dict[str, Any]:
        compact_fields = {
            _REVERSE_FIELD_CODES[field]: self._string_value(extracted_fields.get(field))
            for field in PASSPORT_FIELDS
        }
        compact_input = json.dumps({"f": compact_fields}, separators=(",", ":"), ensure_ascii=False)
        return {
            "systemInstruction": {"parts": [{"text": _SYSTEM_INSTRUCTION}]},
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {"text": compact_input},
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
                "maxOutputTokens": self._settings.gemini_max_output_tokens,
                "thinkingConfig": {"thinkingLevel": "minimal"},
            },
        }

    @staticmethod
    def _extract_provider_json(response_payload: dict[str, Any]) -> dict[str, Any]:
        candidates = response_payload["candidates"]
        text = candidates[0]["content"]["parts"][0]["text"]
        parsed = json.loads(text)
        if not isinstance(parsed, dict) or set(parsed) != {"s", "f"}:
            raise ValueError("Unexpected Gemini response shape")
        if parsed["s"] not in {"match", "changes", "unreadable"} or not isinstance(parsed["f"], list):
            raise ValueError("Unexpected Gemini verification status")
        return parsed

    def _merge(
        self,
        original: dict[str, Any],
        provider_result: dict[str, Any],
    ) -> tuple[dict[str, Any], list[str], list[str]]:
        merged = dict(original)
        corrected: list[str] = []
        filled: list[str] = []
        seen: set[str] = set()

        for item in provider_result["f"]:
            if not isinstance(item, dict) or set(item) != {"k", "v", "a", "c"}:
                raise ValueError("Unexpected field result shape")
            code = item["k"]
            action = item["a"]
            if code not in _FIELD_CODES or action not in _ACTIONS or code in seen:
                raise ValueError("Unexpected or duplicate field result")
            seen.add(code)
            field = _FIELD_CODES[code]
            confidence = float(item["c"])
            if not 0.0 <= confidence <= 1.0:
                raise ValueError("Confidence must be between zero and one")
            value = self._normalize(field, item["v"])
            current = self._string_value(merged.get(field))

            if action == "fill" and not current and value and confidence >= 0.75:
                merged[field] = value
                filled.append(field)
            elif action == "replace" and current and value and value != current and confidence >= 0.90:
                merged[field] = value
                corrected.append(field)

        accepted = corrected + filled
        if accepted:
            sources = dict(merged.get("extraction_sources") or {})
            for field in accepted:
                sources[field] = "gemini_image_verification"
            merged["extraction_sources"] = sources
            merged.pop("processing_note", None)

        merged = normalize_extracted_passport_dates(merged)
        validated_fields = {
            field: value
            for field in PASSPORT_FIELDS
            if (value := self._string_value(merged.get(field)))
        }
        validation = self._validator.validate(validated_fields)
        merged["field_validation"] = {
            "status": validation.status,
            "issues": [
                {"field": issue.field, "message": issue.message, "severity": issue.severity}
                for issue in validation.issues
            ],
        }
        return merged, corrected, filled

    def _normalize(self, field: str, raw_value: Any) -> str:
        value = self._string_value(raw_value)
        if not value:
            return ""
        value = re.sub(r"\s+", " ", value).strip()

        if field in {"surname", "given_names"}:
            normalized = value.upper()
            allowed = all(character.isalpha() or character in " '-." for character in normalized)
            is_plausible = (
                allowed
                and any(character.isalpha() for character in normalized)
                and len(normalized) <= 100
            )
            return normalized if is_plausible else ""
        if field == "passport_number":
            normalized = re.sub(r"\s+", "", value).upper()
            return normalized if re.fullmatch(r"[A-Z0-9]{5,12}", normalized) else ""
        if field in {"nationality", "issuing_country"}:
            normalized = value.upper()
            return normalized if re.fullmatch(r"[A-Z]{3}", normalized) else ""
        if field in {"date_of_birth", "date_of_issue", "date_of_expiry"}:
            try:
                parsed = datetime.strptime(value, "%Y-%m-%d").date()
            except ValueError:
                return ""
            if parsed.year < 1900 or parsed.year > 2100:
                return ""
            if field == "date_of_birth" and parsed >= date.today():
                return ""
            if field == "date_of_issue" and parsed > date.today():
                return ""
            return parsed.isoformat()
        if field == "sex":
            normalized = value.upper()
            normalized = {"MALE": "M", "FEMALE": "F", "UNSPECIFIED": "X"}.get(normalized, normalized)
            return normalized if normalized in {"M", "F", "X", "<"} else ""
        return ""

    def _fallback(
        self,
        original: dict[str, Any],
        *,
        status: str,
        started: float,
    ) -> PassportVerificationResult:
        metadata = self._metadata(status=status, started=started)
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
        provider_status: str | None = None,
    ) -> dict[str, Any]:
        return {
            "status": status,
            "model": self._settings.gemini_model,
            "provider_status": provider_status,
            "corrected_fields": corrected_fields or [],
            "filled_fields": filled_fields or [],
            "duration_ms": round((time.perf_counter() - started) * 1000, 2),
        }

    def _api_key(self) -> str:
        secret = self._settings.google_api_key
        return secret.get_secret_value().strip() if secret else ""

    @staticmethod
    def _safe_content_type(content_type: str) -> str:
        normalized = content_type.lower().strip()
        return normalized if normalized in {"image/jpeg", "image/png", "image/webp"} else "image/jpeg"

    @staticmethod
    def _string_value(value: Any) -> str:
        return value.strip() if isinstance(value, str) else ""
