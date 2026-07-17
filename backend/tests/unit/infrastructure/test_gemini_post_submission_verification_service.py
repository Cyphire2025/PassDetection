"""Unit tests for strict post-submit Gemini verification."""

from __future__ import annotations

import json
import os
import unittest

import httpx

from app.core.config.settings import Settings
from app.infrastructure.ai.gemini_post_submission_verification_service import (
    GeminiPostSubmissionVerificationService,
)

os.environ.setdefault("APP_SECRET_KEY", "test-secret-key")


def _settings(**overrides) -> Settings:  # type: ignore[no-untyped-def]
    values = {
        "app_secret_key": "test-secret-key",
        "google_api_key": "test-google-key",
        "gemini_timeout_seconds": 1.0,
        "gemini_max_retries": 1,
        "_env_file": None,
    }
    values.update(overrides)
    return Settings(**values)


def _submitted_fields() -> dict[str, str]:
    return {
        "surname": "sharma",
        "given_names": "Aman",
        "passport_number": "Z5292389",
        "nationality": "IND",
        "issuing_country": "India",
        "date_of_birth": "1990-01-02",
        "date_of_issue": "2021-03-04",
        "date_of_expiry": "2031-03-03",
        "sex": "M",
    }


def _provider_fields(
    *,
    override: dict[str, dict[str, object]] | None = None,
) -> list[dict[str, object]]:
    observed = {
        "surname": "SHARMA",
        "given_names": "AMAN",
        "passport_number": "Z5292389",
        "nationality": "India",
        "issuing_country": "IND",
        "date_of_birth": "1990-01-02",
        "date_of_issue": "2021-03-04",
        "date_of_expiry": "2031-03-03",
        "sex": "M",
    }
    override = override or {}
    return [
        {
            "field": field,
            "verdict": "correct",
            "observed_value": value,
            "confidence": 0.99,
            "reason_code": "match",
            **override.get(field, {}),
        }
        for field, value in observed.items()
    ]


def _response(
    fields: list[dict[str, object]],
    *,
    thought_signature: str | None = None,
) -> httpx.Response:
    part = {"text": json.dumps({"fields": fields})}
    if thought_signature is not None:
        part["thoughtSignature"] = thought_signature
    return httpx.Response(
        200,
        json={
            "candidates": [
                {
                    "content": {
                        "parts": [part]
                    }
                }
            ]
        },
    )


class GeminiPostSubmissionVerificationServiceTests(
    unittest.IsolatedAsyncioTestCase
):
    async def test_country_name_and_alpha3_are_the_same_identity(self) -> None:
        async def handler(_request: httpx.Request) -> httpx.Response:
            return _response(_provider_fields())

        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler)
        ) as client:
            result = await GeminiPostSubmissionVerificationService(
                settings=_settings(),
                http_client=client,
            ).verify(
                b"passport-image",
                content_type="image/jpeg",
                submitted_fields=_submitted_fields(),
            )

        self.assertEqual(result.decision.value, "ai_approved")
        self.assertEqual(result.to_dict()["incorrect_fields"], [])
        self.assertEqual(result.to_dict()["suspicious_fields"], [])

    async def test_accepts_bounded_thought_signature_metadata(self) -> None:
        async def handler(_request: httpx.Request) -> httpx.Response:
            return _response(
                _provider_fields(),
                thought_signature="opaque-provider-signature",
            )

        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler)
        ) as client:
            result = await GeminiPostSubmissionVerificationService(
                settings=_settings(),
                http_client=client,
            ).verify(
                b"passport-image",
                content_type="image/jpeg",
                submitted_fields=_submitted_fields(),
            )

        self.assertEqual(result.provider_status, "verified")
        self.assertEqual(result.decision.value, "ai_approved")

    async def test_wrong_trailing_letter_is_classified_as_incorrect(self) -> None:
        submitted = _submitted_fields()
        submitted["given_names"] = "YOGESH KUMARK"
        fields = _provider_fields(
            override={
                "given_names": {
                    "verdict": "incorrect",
                    "observed_value": "YOGESH KUMAR",
                    "confidence": 0.99,
                    "reason_code": "different_value",
                }
            }
        )

        async def handler(_request: httpx.Request) -> httpx.Response:
            return _response(
                fields,
                thought_signature="opaque-provider-signature",
            )

        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler)
        ) as client:
            result = await GeminiPostSubmissionVerificationService(
                settings=_settings(),
                http_client=client,
            ).verify(
                b"passport-image",
                content_type="image/jpeg",
                submitted_fields=submitted,
            )

        payload = result.to_dict()
        self.assertEqual(payload["verification_status"], "needs_review")
        self.assertEqual(payload["incorrect_fields"], ["given_names"])
        self.assertEqual(payload["suspicious_fields"], [])
        self.assertEqual(result.model, "gemini-3.5-flash")

    async def test_suspicious_equal_value_cannot_be_upgraded_to_correct(self) -> None:
        fields = _provider_fields(
            override={
                "passport_number": {
                    "verdict": "suspicious",
                    "reason_code": "ambiguous",
                }
            }
        )

        async def handler(_request: httpx.Request) -> httpx.Response:
            return _response(fields)

        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler)
        ) as client:
            result = await GeminiPostSubmissionVerificationService(
                settings=_settings(),
                http_client=client,
            ).verify(
                b"passport-image",
                content_type="image/jpeg",
                submitted_fields=_submitted_fields(),
            )

        self.assertEqual(result.decision.value, "needs_review")
        self.assertIn("passport_number", result.to_dict()["suspicious_fields"])

    async def test_schema_failure_marks_all_nine_fields_suspicious(self) -> None:
        invalid = _provider_fields()
        invalid[0]["confidence"] = "0.99"

        async def handler(_request: httpx.Request) -> httpx.Response:
            return _response(invalid)

        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler)
        ) as client:
            result = await GeminiPostSubmissionVerificationService(
                settings=_settings(),
                http_client=client,
            ).verify(
                b"passport-image",
                content_type="image/jpeg",
                submitted_fields=_submitted_fields(),
            )

        payload = result.to_dict()
        self.assertEqual(payload["verification_status"], "needs_review")
        self.assertEqual(len(payload["suspicious_fields"]), 9)
        self.assertEqual(payload["provider_status"], "invalid_response")

    async def test_zero_retries_and_non_transient_400_do_not_retry(self) -> None:
        for configured_retries, status_code in ((0, 503), (1, 400)):
            with self.subTest(
                configured_retries=configured_retries,
                status_code=status_code,
            ):
                calls = 0

                async def handler(_request: httpx.Request) -> httpx.Response:
                    nonlocal calls
                    calls += 1
                    return httpx.Response(status_code)

                async with httpx.AsyncClient(
                    transport=httpx.MockTransport(handler)
                ) as client:
                    await GeminiPostSubmissionVerificationService(
                        settings=_settings(
                            gemini_max_retries=configured_retries
                        ),
                        http_client=client,
                    ).verify(
                        b"passport-image",
                        content_type="image/jpeg",
                        submitted_fields=_submitted_fields(),
                    )
                self.assertEqual(calls, 1)

    async def test_transient_retry_reuses_one_bounded_payload(self) -> None:
        class Client:
            def __init__(self) -> None:
                self.payload_ids: list[int] = []
                self.prompt_lengths: list[int] = []

            async def post(self, _endpoint: str, **kwargs) -> httpx.Response:  # type: ignore[no-untyped-def]
                payload = kwargs["json"]
                self.payload_ids.append(id(payload))
                submitted = json.loads(
                    payload["contents"][0]["parts"][0]["text"]
                )["submitted_fields"]
                self.prompt_lengths.append(len(submitted["surname"]))
                if len(self.payload_ids) == 1:
                    return httpx.Response(503)
                return _response(_provider_fields())

        client = Client()
        submitted = _submitted_fields()
        submitted["surname"] = "A" * 1000
        result = await GeminiPostSubmissionVerificationService(
            settings=_settings(),
            http_client=client,  # type: ignore[arg-type]
        ).verify(
            b"passport-image",
            content_type="image/jpeg",
            submitted_fields=submitted,
        )

        self.assertEqual(len(client.payload_ids), 2)
        self.assertEqual(len(set(client.payload_ids)), 1)
        self.assertEqual(client.prompt_lengths, [160, 160])
        self.assertEqual(result.decision.value, "needs_review")

    async def test_transient_primary_failure_uses_configured_fallback_model(
        self,
    ) -> None:
        requested_models: list[str] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            requested_models.append(
                str(request.url).split("/models/", 1)[1].split(":", 1)[0]
            )
            if len(requested_models) == 1:
                return httpx.Response(503)
            return _response(
                _provider_fields(),
                thought_signature="opaque-provider-signature",
            )

        settings = _settings().model_copy(
            update={"gemini_fallback_model": "gemini-3.1-flash-lite"}
        )
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler)
        ) as client:
            result = await GeminiPostSubmissionVerificationService(
                settings=settings,
                http_client=client,
            ).verify(
                b"passport-image",
                content_type="image/jpeg",
                submitted_fields=_submitted_fields(),
            )

        self.assertEqual(
            requested_models,
            ["gemini-3.5-flash", "gemini-3.1-flash-lite"],
        )
        self.assertEqual(result.provider_status, "verified")
        self.assertEqual(result.model, "gemini-3.1-flash-lite")
