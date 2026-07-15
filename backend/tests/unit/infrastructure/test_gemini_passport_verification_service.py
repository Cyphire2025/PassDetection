"""Unit tests for bounded, conservative Gemini passport verification."""

from __future__ import annotations

import json
import os
import unittest

import httpx

from app.core.config.settings import Settings
from app.infrastructure.ai.gemini_passport_verification_service import (
    GeminiPassportVerificationService,
)

os.environ.setdefault("APP_SECRET_KEY", "test-secret-key")


def _settings(**overrides) -> Settings:  # type: ignore[no-untyped-def]
    values = {
        "app_secret_key": "test-secret-key",
        "google_api_key": "test-google-key",
        "gemini_timeout_seconds": 1.0,
        "_env_file": None,
    }
    values.update(overrides)
    return Settings(**values)


def _gemini_response(payload: dict) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "candidates": [
                {"content": {"parts": [{"text": json.dumps(payload)}]}}
            ]
        },
    )


class GeminiPassportVerificationServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_sends_compact_json_image_and_secret_header(self) -> None:
        captured: dict[str, object] = {}

        async def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            captured["key"] = request.headers.get("x-goog-api-key")
            captured["body"] = json.loads(request.content)
            return _gemini_response({"s": "match", "f": []})

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await GeminiPassportVerificationService(
                settings=_settings(),
                http_client=client,
            ).verify(
                b"image-bytes",
                content_type="image/jpeg",
                extracted_fields={"surname": "KHANNA"},
            )

        self.assertEqual(result.metadata["status"], "verified")
        self.assertEqual(captured["key"], "test-google-key")
        self.assertNotIn("test-google-key", str(captured["url"]))
        self.assertTrue(str(captured["url"]).endswith("/models/gemini-3.5-flash:generateContent"))
        body = captured["body"]
        assert isinstance(body, dict)
        config = body["generationConfig"]
        self.assertEqual(config["responseMimeType"], "application/json")
        self.assertEqual(config["thinkingConfig"], {"thinkingLevel": "minimal"})
        self.assertLessEqual(config["maxOutputTokens"], 512)
        parts = body["contents"][0]["parts"]
        compact_input = json.loads(parts[0]["text"])
        self.assertEqual(compact_input["f"]["sn"], "KHANNA")
        self.assertEqual(parts[1]["inlineData"]["data"], "aW1hZ2UtYnl0ZXM=")

    async def test_fills_missing_and_replaces_only_high_confidence_valid_values(self) -> None:
        provider = {
            "s": "changes",
            "f": [
                {"k": "gn", "v": "Nipun", "a": "fill", "c": 0.88},
                {"k": "pn", "v": "W7114767", "a": "replace", "c": 0.96},
                {"k": "na", "v": "India", "a": "replace", "c": 0.99},
                {"k": "sx", "v": "F", "a": "replace", "c": 0.60},
            ],
        }

        async def handler(_request: httpx.Request) -> httpx.Response:
            return _gemini_response(provider)

        original = {
            "surname": "VASHISTHA",
            "passport_number": "W7114761",
            "nationality": "IND",
            "sex": "M",
        }
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await GeminiPassportVerificationService(
                settings=_settings(),
                http_client=client,
            ).verify(b"image", content_type="image/jpeg", extracted_fields=original)

        self.assertEqual(result.merged_fields["given_names"], "NIPUN")
        self.assertEqual(result.merged_fields["passport_number"], "W7114767")
        self.assertEqual(result.merged_fields["nationality"], "IND")
        self.assertEqual(result.merged_fields["sex"], "M")
        self.assertEqual(result.metadata["filled_fields"], ["given_names"])
        self.assertEqual(result.metadata["corrected_fields"], ["passport_number"])

    async def test_never_overwrites_nonempty_ocr_with_empty_value(self) -> None:
        async def handler(_request: httpx.Request) -> httpx.Response:
            return _gemini_response(
                {
                    "s": "changes",
                    "f": [{"k": "sn", "v": "", "a": "replace", "c": 1.0}],
                }
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await GeminiPassportVerificationService(
                settings=_settings(),
                http_client=client,
            ).verify(
                b"image",
                content_type="image/jpeg",
                extracted_fields={"surname": "KHANNA"},
            )

        self.assertEqual(result.merged_fields["surname"], "KHANNA")

    async def test_all_empty_ocr_fields_are_filled_from_readable_image_values(self) -> None:
        provider = {
            "s": "changes",
            "f": [
                {"k": "sn", "v": "KHANNA", "a": "fill", "c": 0.97},
                {"k": "gn", "v": "KHUSHI", "a": "fill", "c": 0.97},
                {"k": "pn", "v": "C9391041", "a": "fill", "c": 0.99},
                {"k": "na", "v": "IND", "a": "fill", "c": 0.99},
                {"k": "ic", "v": "IND", "a": "fill", "c": 0.99},
                {"k": "db", "v": "2004-12-15", "a": "fill", "c": 0.98},
                {"k": "de", "v": "2035-03-18", "a": "fill", "c": 0.98},
                {"k": "sx", "v": "F", "a": "fill", "c": 0.96},
            ],
        }

        async def handler(_request: httpx.Request) -> httpx.Response:
            return _gemini_response(provider)

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await GeminiPassportVerificationService(
                settings=_settings(),
                http_client=client,
            ).verify(b"image", content_type="image/jpeg", extracted_fields={})

        self.assertEqual(result.merged_fields["passport_number"], "C9391041")
        self.assertEqual(result.merged_fields["given_names"], "KHUSHI")
        self.assertEqual(len(result.metadata["filled_fields"]), 8)
        self.assertEqual(result.merged_fields["field_validation"]["status"], "valid")

    async def test_invalid_or_unknown_response_falls_back_to_ocr(self) -> None:
        async def handler(_request: httpx.Request) -> httpx.Response:
            return _gemini_response(
                {
                    "s": "changes",
                    "f": [{"k": "unknown", "v": "LEAK", "a": "fill", "c": 1.0}],
                }
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await GeminiPassportVerificationService(
                settings=_settings(),
                http_client=client,
            ).verify(
                b"image",
                content_type="image/jpeg",
                extracted_fields={"surname": "KHANNA"},
            )

        self.assertEqual(result.merged_fields["surname"], "KHANNA")
        self.assertEqual(result.metadata["status"], "invalid_response")
        self.assertNotIn("unknown", result.merged_fields)

    async def test_rate_limit_falls_back_without_retry(self) -> None:
        calls = 0

        async def handler(_request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            return httpx.Response(429, json={"error": {"message": "quota"}})

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await GeminiPassportVerificationService(
                settings=_settings(),
                http_client=client,
            ).verify(
                b"image",
                content_type="image/jpeg",
                extracted_fields={"surname": "KHANNA"},
            )

        self.assertEqual(calls, 1)
        self.assertEqual(result.metadata["status"], "rate_limited")
        self.assertEqual(result.merged_fields["surname"], "KHANNA")

    async def test_missing_key_does_not_make_network_request(self) -> None:
        calls = 0

        async def handler(_request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            return _gemini_response({"s": "match", "f": []})

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await GeminiPassportVerificationService(
                settings=_settings(google_api_key=None),
                http_client=client,
            ).verify(b"image", content_type="image/jpeg", extracted_fields={})

        self.assertEqual(calls, 0)
        self.assertEqual(result.metadata["status"], "not_configured")

    async def test_permission_denied_falls_back_to_ocr(self) -> None:
        async def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(403, json={"error": {"message": "blocked"}})

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await GeminiPassportVerificationService(
                settings=_settings(),
                http_client=client,
            ).verify(
                b"image",
                content_type="image/jpeg",
                extracted_fields={"surname": "KHANNA"},
            )

        self.assertEqual(result.metadata["status"], "permission_denied")
        self.assertEqual(result.merged_fields["surname"], "KHANNA")

    async def test_timeout_falls_back_to_ocr(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("timed out", request=request)

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await GeminiPassportVerificationService(
                settings=_settings(),
                http_client=client,
            ).verify(
                b"image",
                content_type="image/jpeg",
                extracted_fields={"passport_number": "C9391041"},
            )

        self.assertEqual(result.metadata["status"], "timeout")
        self.assertEqual(result.merged_fields["passport_number"], "C9391041")


if __name__ == "__main__":
    unittest.main()
