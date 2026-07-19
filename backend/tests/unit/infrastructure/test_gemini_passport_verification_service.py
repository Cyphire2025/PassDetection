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
from app.infrastructure.ai_priority.metrics import (
    AiPriorityMetrics,
    InMemoryAiMetricsStore,
)
from app.infrastructure.observability.metrics import MetricsRegistry

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
    classified_payload = {
        "d": "passport_data_page",
        "p": "data_page",
        "q": "acceptable",
        "dc": 0.99,
        "r": "passport_confirmed",
        **payload,
    }
    return httpx.Response(
        200,
        json={
            "candidates": [
                {
                    "content": {
                        "parts": [{"text": json.dumps(classified_payload)}]
                    }
                }
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
        self.assertEqual(result.metadata["model"], "gemini-3.5-flash")
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

    async def test_transient_primary_failure_uses_fallback_and_exact_payload(
        self,
    ) -> None:
        class _Client:
            def __init__(self) -> None:
                self.payload_ids: list[int] = []
                self.endpoints: list[str] = []

            async def post(self, endpoint: str, **kwargs) -> httpx.Response:  # type: ignore[no-untyped-def]
                self.endpoints.append(endpoint)
                self.payload_ids.append(id(kwargs["json"]))
                if len(self.payload_ids) == 1:
                    return httpx.Response(503, json={"error": "temporary"})
                return _gemini_response({"s": "match", "f": []})

        client = _Client()
        result = await GeminiPassportVerificationService(
            settings=_settings(),
            http_client=client,  # type: ignore[arg-type]
        ).verify(
            b"one-front-image",
            content_type="image/jpeg",
            extracted_fields={},
        )

        self.assertEqual(result.metadata["status"], "verified")
        self.assertEqual(result.metadata["attempts"], 2)
        self.assertEqual(result.metadata["model"], "gemini-3.1-flash-lite")
        self.assertTrue(
            client.endpoints[0].endswith(
                "/models/gemini-3.5-flash:generateContent"
            )
        )
        self.assertTrue(
            client.endpoints[1].endswith(
                "/models/gemini-3.1-flash-lite:generateContent"
            )
        )
        self.assertEqual(len(client.payload_ids), 2)
        self.assertEqual(len(set(client.payload_ids)), 1)

    async def test_network_failure_uses_fallback_model(self) -> None:
        endpoints: list[str] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            endpoints.append(str(request.url))
            if len(endpoints) == 1:
                raise httpx.ConnectError("temporary network failure", request=request)
            return _gemini_response({"s": "match", "f": []})

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await GeminiPassportVerificationService(
                settings=_settings(),
                http_client=client,
            ).verify(b"image", content_type="image/jpeg", extracted_fields={})

        self.assertEqual(len(endpoints), 2)
        self.assertIn("/models/gemini-3.5-flash:", endpoints[0])
        self.assertIn("/models/gemini-3.1-flash-lite:", endpoints[1])
        self.assertEqual(result.metadata["status"], "verified")
        self.assertEqual(result.metadata["model"], "gemini-3.1-flash-lite")

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

    async def test_explicit_absent_surname_stays_empty_and_never_copies_given_name(
        self,
    ) -> None:
        provider = {
            "s": "changes",
            "f": [
                {"k": "sn", "v": "", "a": "absent", "c": 0.99},
                {"k": "gn", "v": "MOHIT", "a": "fill", "c": 0.99},
                {"k": "pn", "v": "W6905713", "a": "fill", "c": 0.99},
                {"k": "na", "v": "IND", "a": "fill", "c": 0.99},
                {"k": "ic", "v": "IND", "a": "fill", "c": 0.99},
                {"k": "db", "v": "1998-09-08", "a": "fill", "c": 0.99},
                {"k": "di", "v": "2023-04-13", "a": "fill", "c": 0.99},
                {"k": "de", "v": "2033-04-12", "a": "fill", "c": 0.99},
                {"k": "sx", "v": "M", "a": "fill", "c": 0.99},
            ],
        }

        async def handler(request: httpx.Request) -> httpx.Response:
            payload = json.loads(request.content)
            actions = payload["generationConfig"]["responseSchema"][
                "properties"
            ]["f"]["items"]["properties"]["a"]["enum"]
            self.assertIn("absent", actions)
            system_text = payload["systemInstruction"]["parts"][0]["text"]
            self.assertIn("Never copy the given names into surname", system_text)
            self.assertIn("unreadable, obscured, or ambiguous", system_text)
            return _gemini_response(provider)

        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler)
        ) as client:
            result = await GeminiPassportVerificationService(
                settings=_settings(),
                http_client=client,
            ).verify(
                b"image",
                content_type="image/jpeg",
                extracted_fields={"surname": "MOHIT"},
            )

        self.assertIn("surname", result.merged_fields)
        self.assertEqual(result.merged_fields["surname"], "")
        self.assertEqual(result.merged_fields["given_names"], "MOHIT")
        self.assertEqual(result.metadata["absent_fields"], ["surname"])
        self.assertIn("surname", result.metadata["corrected_fields"])
        self.assertNotIn(
            "surname",
            {
                issue["field"]
                for issue in result.merged_fields["field_validation"]["issues"]
            },
        )

    async def test_provider_cannot_copy_filled_given_name_into_blank_surname(
        self,
    ) -> None:
        provider = {
            "s": "changes",
            "f": [
                {"k": "sn", "v": "MOHIT", "a": "fill", "c": 0.99},
                {"k": "gn", "v": "MOHIT", "a": "fill", "c": 0.99},
                {"k": "pn", "v": "W6905713", "a": "fill", "c": 0.99},
            ],
        }

        async def handler(_request: httpx.Request) -> httpx.Response:
            return _gemini_response(provider)

        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler)
        ) as client:
            result = await GeminiPassportVerificationService(
                settings=_settings(),
                http_client=client,
            ).verify(
                b"image",
                content_type="image/jpeg",
                extracted_fields={"surname": ""},
            )

        self.assertIn("surname", result.merged_fields)
        self.assertEqual(result.merged_fields["surname"], "")
        self.assertEqual(result.merged_fields["given_names"], "MOHIT")
        self.assertNotIn("surname", result.metadata["filled_fields"])
        self.assertEqual(result.metadata["absent_fields"], [])
        self.assertIn(
            "surname",
            {
                issue["field"]
                for issue in result.merged_fields["field_validation"]["issues"]
            },
        )

    async def test_reextraction_cannot_copy_kept_given_name_into_blank_surname(
        self,
    ) -> None:
        provider = {
            "s": "changes",
            "f": [
                {"k": "sn", "v": "MOHIT", "a": "fill", "c": 0.99},
                {"k": "gn", "v": "MOHIT", "a": "keep", "c": 0.99},
            ],
        }

        async def handler(_request: httpx.Request) -> httpx.Response:
            return _gemini_response(provider)

        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler)
        ) as client:
            result = await GeminiPassportVerificationService(
                settings=_settings(),
                http_client=client,
            ).verify(
                b"image",
                content_type="image/jpeg",
                extracted_fields={
                    "surname": "",
                    "given_names": "MOHIT",
                },
            )

        self.assertEqual(result.merged_fields["surname"], "")
        self.assertEqual(result.merged_fields["given_names"], "MOHIT")
        self.assertNotIn("surname", result.metadata["filled_fields"])
        self.assertEqual(result.metadata["absent_fields"], [])

    async def test_reextraction_cannot_copy_replaced_given_name_into_blank_surname(
        self,
    ) -> None:
        provider = {
            "s": "changes",
            "f": [
                {"k": "sn", "v": "ANITA", "a": "fill", "c": 0.99},
                {"k": "gn", "v": "ANITA", "a": "replace", "c": 0.99},
            ],
        }

        async def handler(_request: httpx.Request) -> httpx.Response:
            return _gemini_response(provider)

        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler)
        ) as client:
            result = await GeminiPassportVerificationService(
                settings=_settings(),
                http_client=client,
            ).verify(
                b"image",
                content_type="image/jpeg",
                extracted_fields={
                    "surname": "",
                    "given_names": "MOHIT",
                },
            )

        self.assertEqual(result.merged_fields["surname"], "")
        self.assertEqual(result.merged_fields["given_names"], "ANITA")
        self.assertNotIn("surname", result.metadata["filled_fields"])
        self.assertEqual(result.metadata["absent_fields"], [])

    async def test_low_confidence_absent_surname_does_not_clear_existing_value(
        self,
    ) -> None:
        async def handler(_request: httpx.Request) -> httpx.Response:
            return _gemini_response(
                {
                    "s": "changes",
                    "f": [{"k": "sn", "v": "", "a": "absent", "c": 0.70}],
                }
            )

        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler)
        ) as client:
            result = await GeminiPassportVerificationService(
                settings=_settings(),
                http_client=client,
            ).verify(
                b"image",
                content_type="image/jpeg",
                extracted_fields={"surname": "KHANNA"},
            )

        self.assertEqual(result.merged_fields["surname"], "KHANNA")
        self.assertEqual(result.metadata["absent_fields"], [])

    async def test_invalid_absent_action_combinations_fail_closed(self) -> None:
        invalid_fields = (
            {"k": "gn", "v": "", "a": "absent", "c": 0.99},
            {"k": "sn", "v": "MOHIT", "a": "absent", "c": 0.99},
        )
        for invalid in invalid_fields:
            with self.subTest(invalid=invalid):
                async def handler(
                    _request: httpx.Request,
                    item: dict[str, object] = invalid,
                ) -> httpx.Response:
                    return _gemini_response(
                        {"s": "changes", "f": [item]}
                    )

                async with httpx.AsyncClient(
                    transport=httpx.MockTransport(handler)
                ) as client:
                    result = await GeminiPassportVerificationService(
                        settings=_settings(),
                        http_client=client,
                    ).verify(
                        b"image",
                        content_type="image/jpeg",
                        extracted_fields={"surname": "KHANNA"},
                    )

                self.assertEqual(result.metadata["status"], "invalid_response")
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
                {"k": "di", "v": "2025-03-18", "a": "fill", "c": 0.96},
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
        self.assertEqual(len(result.metadata["filled_fields"]), 9)
        self.assertEqual(
            result.metadata["field_confidences"]["passport_number"],
            0.99,
        )
        self.assertEqual(len(result.metadata["field_confidences"]), 9)
        self.assertEqual(result.merged_fields["date_of_issue"], "2025-03-18")
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

    async def test_high_confidence_passport_cover_is_rejected_safely(self) -> None:
        async def handler(_request: httpx.Request) -> httpx.Response:
            return _gemini_response(
                {
                    "d": "passport_cover",
                    "p": "cover",
                    "dc": 0.98,
                    "r": "passport_cover",
                    "s": "unreadable",
                    "f": [],
                }
            )

        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler)
        ) as client:
            result = await GeminiPassportVerificationService(
                settings=_settings(),
                http_client=client,
            ).verify(
                b"cover-image",
                content_type="image/jpeg",
                extracted_fields={"surname": "LOCAL OCR"},
            )

        self.assertEqual(result.metadata["status"], "passport_cover")
        self.assertEqual(result.metadata["document_class"], "passport_cover")
        self.assertEqual(result.metadata["reason_code"], "passport_cover")
        self.assertFalse(result.metadata["available"])
        self.assertEqual(result.merged_fields["surname"], "LOCAL OCR")

    async def test_high_confidence_aadhaar_is_wrong_document(self) -> None:
        async def handler(_request: httpx.Request) -> httpx.Response:
            return _gemini_response(
                {
                    "d": "aadhaar",
                    "p": "not_applicable",
                    "dc": 0.97,
                    "r": "wrong_document",
                    "s": "unreadable",
                    "f": [],
                }
            )

        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler)
        ) as client:
            result = await GeminiPassportVerificationService(
                settings=_settings(),
                http_client=client,
            ).verify(b"aadhaar-image", content_type="image/jpeg", extracted_fields={})

        self.assertEqual(result.metadata["status"], "wrong_document")
        self.assertEqual(result.metadata["document_class"], "aadhaar")
        self.assertNotIn("processing_note", result.merged_fields)

    async def test_uncertain_document_classification_stays_generic(self) -> None:
        async def handler(_request: httpx.Request) -> httpx.Response:
            return _gemini_response(
                {
                    "d": "uncertain",
                    "p": "unknown",
                    "dc": 0.42,
                    "r": "classification_uncertain",
                    "s": "unreadable",
                    "f": [],
                }
            )

        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler)
        ) as client:
            result = await GeminiPassportVerificationService(
                settings=_settings(),
                http_client=client,
            ).verify(b"unclear-image", content_type="image/jpeg", extracted_fields={})

        self.assertEqual(result.metadata["status"], "document_uncertain")
        self.assertEqual(result.metadata["reason_code"], "classification_uncertain")

    async def test_rate_limit_retries_once_then_falls_back(self) -> None:
        endpoints: list[str] = []
        shared_metrics = InMemoryAiMetricsStore()

        async def handler(request: httpx.Request) -> httpx.Response:
            endpoints.append(str(request.url))
            return httpx.Response(429, json={"error": {"message": "quota"}})

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await GeminiPassportVerificationService(
                settings=_settings(),
                http_client=client,
                priority_metrics=AiPriorityMetrics(
                    MetricsRegistry(),
                    shared_metrics,
                ),
            ).verify(
                b"image",
                content_type="image/jpeg",
                extracted_fields={"surname": "KHANNA"},
            )

        self.assertEqual(len(endpoints), 2)
        self.assertIn("/models/gemini-3.5-flash:", endpoints[0])
        self.assertIn("/models/gemini-3.1-flash-lite:", endpoints[1])
        self.assertEqual(result.metadata["attempts"], 2)
        self.assertEqual(result.metadata["status"], "rate_limited")
        self.assertEqual(result.metadata["model"], "gemini-3.1-flash-lite")
        self.assertEqual(result.merged_fields["surname"], "KHANNA")
        counters = shared_metrics.snapshot()["counters"]
        self.assertEqual(
            counters["ai_provider.events.total.extraction.upstream_429"],
            2,
        )
        self.assertEqual(
            counters["ai_provider.events.total.extraction.retry"],
            1,
        )

    async def test_zero_retries_does_not_attempt_fallback(self) -> None:
        endpoints: list[str] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            endpoints.append(str(request.url))
            return httpx.Response(503, json={"error": {"message": "busy"}})

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await GeminiPassportVerificationService(
                settings=_settings(gemini_max_retries=0),
                http_client=client,
            ).verify(
                b"image",
                content_type="image/jpeg",
                extracted_fields={"surname": "KHANNA"},
            )

        self.assertEqual(len(endpoints), 1)
        self.assertIn("/models/gemini-3.5-flash:", endpoints[0])
        self.assertEqual(result.metadata["attempts"], 1)
        self.assertEqual(result.metadata["status"], "provider_unavailable")
        self.assertEqual(result.metadata["model"], "gemini-3.5-flash")

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

    async def test_post_submit_flag_does_not_disable_interactive_gemini(
        self,
    ) -> None:
        calls = 0

        async def handler(_request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            return _gemini_response({"s": "match", "f": []})

        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler)
        ) as client:
            result = await GeminiPassportVerificationService(
                settings=_settings(gemini_verification_enabled=False),
                http_client=client,
            ).verify(
                b"image",
                content_type="image/jpeg",
                extracted_fields={"surname": "KHANNA"},
            )

        self.assertEqual(calls, 1)
        self.assertEqual(result.metadata["status"], "verified")

    async def test_permission_denied_falls_back_to_ocr(self) -> None:
        calls = 0

        async def handler(_request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
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

        self.assertEqual(calls, 1)
        self.assertEqual(result.metadata["status"], "permission_denied")
        self.assertEqual(result.metadata["model"], "gemini-3.5-flash")
        self.assertEqual(result.merged_fields["surname"], "KHANNA")

    async def test_rejected_request_does_not_attempt_fallback(self) -> None:
        endpoints: list[str] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            endpoints.append(str(request.url))
            return httpx.Response(400, json={"error": {"message": "bad request"}})

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await GeminiPassportVerificationService(
                settings=_settings(),
                http_client=client,
            ).verify(
                b"image",
                content_type="image/jpeg",
                extracted_fields={"surname": "KHANNA"},
            )

        self.assertEqual(len(endpoints), 1)
        self.assertIn("/models/gemini-3.5-flash:", endpoints[0])
        self.assertEqual(result.metadata["status"], "provider_rejected_request")
        self.assertEqual(result.metadata["model"], "gemini-3.5-flash")

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
        self.assertEqual(result.metadata["attempts"], 2)
        self.assertEqual(result.metadata["model"], "gemini-3.1-flash-lite")
        self.assertEqual(result.merged_fields["passport_number"], "C9391041")


if __name__ == "__main__":
    unittest.main()
