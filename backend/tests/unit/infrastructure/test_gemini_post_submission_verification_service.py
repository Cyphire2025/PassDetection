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
        "place_of_issue": "Chennai",
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
        "place_of_issue": "CHENNAI",
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


def _provider_document(
    **overrides: object,
) -> dict[str, object]:
    document: dict[str, object] = {
        "document_class": "passport_data_page",
        "page_type": "data_page",
        "image_quality": "acceptable",
        "classification_confidence": 0.99,
        "reason_code": "passport_confirmed",
    }
    document.update(overrides)
    return document


def _response(
    fields: list[dict[str, object]],
    *,
    document: dict[str, object] | None = None,
    thought_signature: str | None = None,
) -> httpx.Response:
    part = {
        "text": json.dumps(
            {
                "document": (document if document is not None else _provider_document()),
                "fields": fields,
            }
        )
    }
    if thought_signature is not None:
        part["thoughtSignature"] = thought_signature
    return httpx.Response(
        200,
        json={"candidates": [{"content": {"parts": [part]}}]},
    )


class GeminiPostSubmissionVerificationServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_place_of_issue_is_compared_as_visible_free_text(self) -> None:
        async def handler(_request: httpx.Request) -> httpx.Response:
            return _response(_provider_fields())

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
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
        self.assertIsNone(result.reason_code)

    async def test_legacy_issuing_country_is_not_sent_as_place_of_issue(self) -> None:
        submitted = _submitted_fields()
        submitted.pop("place_of_issue")
        submitted["issuing_country"] = "Chennai"

        async def handler(request: httpx.Request) -> httpx.Response:
            payload = json.loads(request.content)
            prompt_fields = json.loads(payload["contents"][0]["parts"][0]["text"])[
                "submitted_fields"
            ]
            self.assertEqual(prompt_fields["place_of_issue"], "")
            self.assertNotIn("issuing_country", prompt_fields)
            return _response(_provider_fields())

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await GeminiPostSubmissionVerificationService(
                settings=_settings(),
                http_client=client,
            ).verify(
                b"passport-image",
                content_type="image/jpeg",
                submitted_fields=submitted,
            )

        self.assertEqual(result.decision.value, "needs_review")

    async def test_visibly_absent_surname_is_correct_and_ai_approved(self) -> None:
        submitted = _submitted_fields()
        submitted["surname"] = ""
        fields = _provider_fields(
            override={
                "surname": {
                    "verdict": "correct",
                    "observed_value": "",
                    "confidence": 0.99,
                    "reason_code": "not_present",
                }
            }
        )

        async def handler(request: httpx.Request) -> httpx.Response:
            payload = json.loads(request.content)
            reason_codes = payload["generationConfig"]["responseSchema"]["properties"]["fields"][
                "items"
            ]["properties"]["reason_code"]["enum"]
            self.assertIn("not_present", reason_codes)
            system_text = payload["systemInstruction"]["parts"][0]["text"]
            self.assertIn("Never copy given names into surname", system_text)
            self.assertIn("reason_code not_present", system_text)
            return _response(fields)

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await GeminiPostSubmissionVerificationService(
                settings=_settings(),
                http_client=client,
            ).verify(
                b"passport-image",
                content_type="image/jpeg",
                submitted_fields=submitted,
            )

        surname = next(field for field in result.fields if field.field == "surname")
        self.assertEqual(result.decision.value, "ai_approved")
        self.assertEqual(result.to_dict()["suspicious_fields"], [])
        self.assertEqual(surname.verdict.value, "correct")
        self.assertIsNone(surname.observed_value)
        self.assertEqual(surname.reason_code, "not_present")
        self.assertEqual(surname.confidence, 0.99)

    async def test_empty_surname_with_unreadable_evidence_still_needs_review(
        self,
    ) -> None:
        submitted = _submitted_fields()
        submitted["surname"] = ""
        fields = _provider_fields(
            override={
                "surname": {
                    "verdict": "suspicious",
                    "observed_value": "",
                    "confidence": 0.99,
                    "reason_code": "unreadable",
                }
            }
        )

        async def handler(_request: httpx.Request) -> httpx.Response:
            return _response(fields)

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await GeminiPostSubmissionVerificationService(
                settings=_settings(),
                http_client=client,
            ).verify(
                b"passport-image",
                content_type="image/jpeg",
                submitted_fields=submitted,
            )

        surname = next(field for field in result.fields if field.field == "surname")
        self.assertEqual(result.decision.value, "needs_review")
        self.assertEqual(result.to_dict()["suspicious_fields"], ["surname"])
        self.assertEqual(surname.reason_code, "unreadable")
        self.assertEqual(surname.confidence, 0.0)

    async def test_omitted_surname_that_is_visibly_present_is_incorrect(
        self,
    ) -> None:
        submitted = _submitted_fields()
        submitted["surname"] = ""

        async def handler(_request: httpx.Request) -> httpx.Response:
            return _response(_provider_fields())

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await GeminiPostSubmissionVerificationService(
                settings=_settings(),
                http_client=client,
            ).verify(
                b"passport-image",
                content_type="image/jpeg",
                submitted_fields=submitted,
            )

        surname = next(field for field in result.fields if field.field == "surname")
        self.assertEqual(result.decision.value, "needs_review")
        self.assertEqual(result.to_dict()["incorrect_fields"], ["surname"])
        self.assertEqual(surname.reason_code, "different_value")

    async def test_low_confidence_absent_surname_still_needs_review(self) -> None:
        submitted = _submitted_fields()
        submitted["surname"] = ""
        fields = _provider_fields(
            override={
                "surname": {
                    "verdict": "correct",
                    "observed_value": "",
                    "confidence": 0.70,
                    "reason_code": "not_present",
                }
            }
        )

        async def handler(_request: httpx.Request) -> httpx.Response:
            return _response(fields)

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await GeminiPostSubmissionVerificationService(
                settings=_settings(),
                http_client=client,
            ).verify(
                b"passport-image",
                content_type="image/jpeg",
                submitted_fields=submitted,
            )

        surname = next(field for field in result.fields if field.field == "surname")
        self.assertEqual(result.decision.value, "needs_review")
        self.assertEqual(surname.verdict.value, "suspicious")
        self.assertEqual(surname.reason_code, "low_confidence")

    async def test_invalid_not_present_combinations_fail_closed(self) -> None:
        cases = (
            {
                "given_names": {
                    "verdict": "correct",
                    "observed_value": "",
                    "confidence": 0.99,
                    "reason_code": "not_present",
                }
            },
            {
                "surname": {
                    "verdict": "correct",
                    "observed_value": "SHARMA",
                    "confidence": 0.99,
                    "reason_code": "not_present",
                }
            },
        )
        for override in cases:
            with self.subTest(override=override):

                async def handler(
                    _request: httpx.Request,
                    provider_override: dict[
                        str,
                        dict[str, object],
                    ] = override,
                ) -> httpx.Response:
                    return _response(_provider_fields(override=provider_override))

                async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                    result = await GeminiPostSubmissionVerificationService(
                        settings=_settings(),
                        http_client=client,
                    ).verify(
                        b"passport-image",
                        content_type="image/jpeg",
                        submitted_fields=_submitted_fields(),
                    )

                self.assertEqual(result.decision.value, "needs_review")
                self.assertEqual(result.provider_status, "invalid_response")
                self.assertEqual(len(result.to_dict()["suspicious_fields"]), 9)

    async def test_request_uses_strict_document_and_field_schema(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            payload = json.loads(request.content)
            schema = payload["generationConfig"]["responseSchema"]
            self.assertEqual(
                set(schema["properties"]),
                {"document", "fields"},
            )
            self.assertEqual(
                schema["required"],
                ["document", "fields"],
            )
            self.assertEqual(
                set(schema["properties"]["document"]["required"]),
                {
                    "document_class",
                    "page_type",
                    "image_quality",
                    "classification_confidence",
                    "reason_code",
                },
            )
            system_text = payload["systemInstruction"]["parts"][0]["text"]
            self.assertIn("First classify the image", system_text)
            self.assertIn("Never infer hidden values", system_text)
            self.assertIn(
                "Never infer hidden values or decide the application's final status",
                system_text,
            )
            self.assertIn("For place_of_issue", system_text)
            self.assertIn("do not substitute, infer, or return an issuing country", system_text)
            submitted = json.loads(payload["contents"][0]["parts"][0]["text"])["submitted_fields"]
            self.assertEqual(submitted["place_of_issue"], "Chennai")
            self.assertNotIn("issuing_country", submitted)
            return _response(_provider_fields())

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await GeminiPostSubmissionVerificationService(
                settings=_settings(),
                http_client=client,
            ).verify(
                b"passport-image",
                content_type="image/jpeg",
                submitted_fields=_submitted_fields(),
            )

        self.assertEqual(result.decision.value, "ai_approved")
        self.assertEqual(result.provider_status, "verified")

    async def test_document_classification_requires_exact_bounded_shape(
        self,
    ) -> None:
        missing_key = _provider_document()
        missing_key.pop("page_type")
        extra_key = _provider_document(extra="not-allowed")
        invalid_confidence = _provider_document(
            classification_confidence=True,
        )

        for label, document in (
            ("missing", missing_key),
            ("extra", extra_key),
            ("invalid-confidence", invalid_confidence),
        ):
            with self.subTest(label=label):

                async def handler(
                    _request: httpx.Request,
                    response_document: dict[str, object] = document,
                ) -> httpx.Response:
                    return _response(
                        _provider_fields(),
                        document=response_document,
                    )

                async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                    result = await GeminiPostSubmissionVerificationService(
                        settings=_settings(),
                        http_client=client,
                    ).verify(
                        b"passport-image",
                        content_type="image/jpeg",
                        submitted_fields=_submitted_fields(),
                    )

                self.assertEqual(result.decision.value, "needs_review")
                self.assertEqual(result.provider_status, "invalid_response")
                self.assertEqual(
                    result.reason_code,
                    "invalid_provider_response",
                )

    async def test_wrong_document_and_wrong_passport_page_override_field_matches(
        self,
    ) -> None:
        cases = (
            (
                "aadhaar",
                _provider_document(
                    document_class="aadhaar",
                    page_type="not_applicable",
                    classification_confidence=0.99,
                    reason_code="wrong_document",
                ),
                "wrong_document",
                "does not appear to be a passport information page",
            ),
            (
                "cover",
                _provider_document(
                    document_class="passport_cover",
                    page_type="cover",
                    classification_confidence=0.98,
                    reason_code="passport_cover",
                ),
                "passport_cover",
                "appears to be a passport cover",
            ),
            (
                "other-page",
                _provider_document(
                    document_class="passport_other_page",
                    page_type="other_passport_page",
                    classification_confidence=0.97,
                    reason_code="wrong_passport_page",
                ),
                "wrong_passport_page",
                "appears to be a different passport page",
            ),
        )

        for label, document, reason_code, explanation in cases:
            with self.subTest(label=label):

                async def handler(
                    _request: httpx.Request,
                    response_document: dict[str, object] = document,
                ) -> httpx.Response:
                    return _response(
                        _provider_fields(),
                        document=response_document,
                    )

                async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                    result = await GeminiPostSubmissionVerificationService(
                        settings=_settings(),
                        http_client=client,
                    ).verify(
                        b"passport-image",
                        content_type="image/jpeg",
                        submitted_fields=_submitted_fields(),
                    )

                self.assertEqual(result.decision.value, "needs_review")
                self.assertEqual(result.provider_status, "verified")
                self.assertEqual(result.reason_code, reason_code)
                self.assertIn(explanation, result.explanation)

    async def test_low_quality_unreadable_and_uncertain_images_require_review(
        self,
    ) -> None:
        cases = (
            (
                "low-quality",
                _provider_document(
                    image_quality="low_quality",
                    reason_code="low_image_quality",
                ),
                "document_low_quality",
                "too low quality",
            ),
            (
                "unreadable",
                _provider_document(
                    image_quality="unreadable",
                    reason_code="low_image_quality",
                ),
                "document_unreadable",
                "is unreadable",
            ),
            (
                "uncertain",
                _provider_document(
                    document_class="uncertain",
                    page_type="unknown",
                    classification_confidence=0.45,
                    reason_code="classification_uncertain",
                ),
                "document_uncertain",
                "classification is uncertain",
            ),
        )

        for label, document, reason_code, explanation in cases:
            with self.subTest(label=label):

                async def handler(
                    _request: httpx.Request,
                    response_document: dict[str, object] = document,
                ) -> httpx.Response:
                    return _response(
                        _provider_fields(),
                        document=response_document,
                    )

                async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                    result = await GeminiPostSubmissionVerificationService(
                        settings=_settings(),
                        http_client=client,
                    ).verify(
                        b"passport-image",
                        content_type="image/jpeg",
                        submitted_fields=_submitted_fields(),
                    )

                self.assertEqual(result.decision.value, "needs_review")
                self.assertEqual(result.provider_status, "verified")
                self.assertEqual(result.reason_code, reason_code)
                self.assertIn(explanation, result.explanation)

    async def test_normalizes_common_printed_passport_date_formats(self) -> None:
        submitted = _submitted_fields()
        submitted.update(
            {
                "date_of_birth": "1972-08-30",
                "date_of_issue": "2023-08-10",
                "date_of_expiry": "2033-08-09",
            }
        )
        fields = _provider_fields(
            override={
                "date_of_birth": {"observed_value": "30/08/1972"},
                "date_of_issue": {"observed_value": "10/08/2023"},
                "date_of_expiry": {"observed_value": "09/08/2033"},
            }
        )

        async def handler(_request: httpx.Request) -> httpx.Response:
            return _response(fields)

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await GeminiPostSubmissionVerificationService(
                settings=_settings(),
                http_client=client,
            ).verify(
                b"passport-image",
                content_type="image/jpeg",
                submitted_fields=submitted,
            )

        self.assertEqual(result.decision.value, "ai_approved")
        self.assertEqual(result.to_dict()["suspicious_fields"], [])

    async def test_ambiguous_numeric_date_requires_review(self) -> None:
        fields = _provider_fields(
            override={
                "date_of_issue": {
                    "observed_value": "03/04/2021",
                    "confidence": 1.0,
                }
            }
        )

        async def handler(_request: httpx.Request) -> httpx.Response:
            return _response(fields)

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await GeminiPostSubmissionVerificationService(
                settings=_settings(),
                http_client=client,
            ).verify(
                b"passport-image",
                content_type="image/jpeg",
                submitted_fields=_submitted_fields(),
            )

        date_result = next(field for field in result.fields if field.field == "date_of_issue")
        self.assertEqual(result.decision.value, "needs_review")
        self.assertEqual(date_result.verdict.value, "suspicious")
        self.assertEqual(date_result.reason_code, "ambiguous")
        self.assertEqual(date_result.confidence, 0.0)

    async def test_submitted_dates_remain_strictly_canonical_iso(self) -> None:
        submitted = _submitted_fields()
        submitted["date_of_birth"] = "02/01/1990"

        async def handler(_request: httpx.Request) -> httpx.Response:
            return _response(_provider_fields())

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await GeminiPostSubmissionVerificationService(
                settings=_settings(),
                http_client=client,
            ).verify(
                b"passport-image",
                content_type="image/jpeg",
                submitted_fields=submitted,
            )

        date_result = next(field for field in result.fields if field.field == "date_of_birth")
        self.assertEqual(result.decision.value, "needs_review")
        self.assertEqual(date_result.reason_code, "missing_submitted_value")
        self.assertEqual(date_result.confidence, 0.0)

    async def test_unreadable_evidence_never_reports_full_confidence(self) -> None:
        fields = _provider_fields(
            override={
                "date_of_issue": {
                    "verdict": "suspicious",
                    "observed_value": "",
                    "confidence": 1.0,
                    "reason_code": "unreadable",
                }
            }
        )

        async def handler(_request: httpx.Request) -> httpx.Response:
            return _response(fields)

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await GeminiPostSubmissionVerificationService(
                settings=_settings(),
                http_client=client,
            ).verify(
                b"passport-image",
                content_type="image/jpeg",
                submitted_fields=_submitted_fields(),
            )

        date_result = next(field for field in result.fields if field.field == "date_of_issue")
        self.assertEqual(date_result.reason_code, "unreadable")
        self.assertEqual(date_result.confidence, 0.0)
        self.assertLess(result.confidence, 1.0)

    async def test_all_unreadable_evidence_has_zero_verification_confidence(
        self,
    ) -> None:
        fields = _provider_fields()
        for field in fields:
            field.update(
                {
                    "verdict": "suspicious",
                    "observed_value": "",
                    "confidence": 1.0,
                    "reason_code": "unreadable",
                }
            )

        async def handler(_request: httpx.Request) -> httpx.Response:
            return _response(fields)

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await GeminiPostSubmissionVerificationService(
                settings=_settings(),
                http_client=client,
            ).verify(
                b"passport-image",
                content_type="image/jpeg",
                submitted_fields=_submitted_fields(),
            )

        self.assertEqual(result.decision.value, "needs_review")
        self.assertEqual(result.confidence, 0.0)
        self.assertTrue(all(field.confidence == 0.0 for field in result.fields))

    async def test_accepts_bounded_thought_signature_metadata(self) -> None:
        async def handler(_request: httpx.Request) -> httpx.Response:
            return _response(
                _provider_fields(),
                thought_signature="opaque-provider-signature",
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
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

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
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

    async def test_application_marks_normalized_equal_value_correct(self) -> None:
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

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await GeminiPostSubmissionVerificationService(
                settings=_settings(),
                http_client=client,
            ).verify(
                b"passport-image",
                content_type="image/jpeg",
                submitted_fields=_submitted_fields(),
            )

        self.assertEqual(result.decision.value, "ai_approved")
        self.assertEqual(result.to_dict()["suspicious_fields"], [])

    async def test_indian_display_label_matches_ind_alpha3(self) -> None:
        submitted = _submitted_fields()
        submitted["nationality"] = "Indian"
        fields = _provider_fields(
            override={
                "nationality": {
                    "verdict": "suspicious",
                    "observed_value": "IND",
                    "confidence": 0.99,
                    "reason_code": "ambiguous",
                }
            }
        )

        async def handler(_request: httpx.Request) -> httpx.Response:
            return _response(fields)

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await GeminiPostSubmissionVerificationService(
                settings=_settings(),
                http_client=client,
            ).verify(
                b"passport-image",
                content_type="image/jpeg",
                submitted_fields=submitted,
            )

        nationality = next(field for field in result.fields if field.field == "nationality")
        self.assertEqual(result.decision.value, "ai_approved")
        self.assertEqual(nationality.verdict.value, "correct")
        self.assertEqual(nationality.reason_code, "match")

    async def test_equal_value_with_low_visual_confidence_still_needs_review(
        self,
    ) -> None:
        fields = _provider_fields(
            override={
                "passport_number": {
                    "verdict": "suspicious",
                    "confidence": 0.60,
                    "reason_code": "ambiguous",
                }
            }
        )

        async def handler(_request: httpx.Request) -> httpx.Response:
            return _response(fields)

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await GeminiPostSubmissionVerificationService(
                settings=_settings(),
                http_client=client,
            ).verify(
                b"passport-image",
                content_type="image/jpeg",
                submitted_fields=_submitted_fields(),
            )

        passport_number = next(field for field in result.fields if field.field == "passport_number")
        self.assertEqual(result.decision.value, "needs_review")
        self.assertEqual(passport_number.verdict.value, "suspicious")
        self.assertEqual(passport_number.reason_code, "low_confidence")

    async def test_schema_failure_marks_all_nine_fields_suspicious(self) -> None:
        invalid = _provider_fields()
        invalid[0]["confidence"] = "0.99"

        async def handler(_request: httpx.Request) -> httpx.Response:
            return _response(invalid)

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
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

                async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                    await GeminiPostSubmissionVerificationService(
                        settings=_settings(gemini_max_retries=configured_retries),
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
                submitted = json.loads(payload["contents"][0]["parts"][0]["text"])[
                    "submitted_fields"
                ]
                self.prompt_lengths.append(len(submitted["surname"]))
                if len(self.payload_ids) == 1:
                    return httpx.Response(503)
                return _response(_provider_fields())

        client = Client()
        shared_metrics = InMemoryAiMetricsStore()
        submitted = _submitted_fields()
        submitted["surname"] = "A" * 1000
        result = await GeminiPostSubmissionVerificationService(
            settings=_settings(),
            http_client=client,  # type: ignore[arg-type]
            priority_metrics=AiPriorityMetrics(
                MetricsRegistry(),
                shared_metrics,
            ),
        ).verify(
            b"passport-image",
            content_type="image/jpeg",
            submitted_fields=submitted,
        )

        self.assertEqual(len(client.payload_ids), 2)
        self.assertEqual(len(set(client.payload_ids)), 1)
        self.assertEqual(client.prompt_lengths, [160, 160])
        self.assertEqual(result.decision.value, "needs_review")
        counters = shared_metrics.snapshot()["counters"]
        self.assertEqual(
            counters["ai_provider.events.total.verification.upstream_failure"],
            1,
        )
        self.assertEqual(
            counters["ai_provider.events.total.verification.retry"],
            1,
        )
        self.assertEqual(
            counters["ai_provider.events.total.verification.success"],
            1,
        )

    async def test_transient_primary_failure_uses_configured_fallback_model(
        self,
    ) -> None:
        requested_models: list[str] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            requested_models.append(str(request.url).split("/models/", 1)[1].split(":", 1)[0])
            if len(requested_models) == 1:
                return httpx.Response(503)
            return _response(
                _provider_fields(),
                thought_signature="opaque-provider-signature",
            )

        settings = _settings().model_copy(update={"gemini_fallback_model": "gemini-3.1-flash-lite"})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
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

    async def test_gemini_36_thinking_level_is_changed_for_older_fallback(
        self,
    ) -> None:
        requests: list[tuple[str, str]] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            model = str(request.url).split("/models/", 1)[1].split(":", 1)[0]
            requests.append((model, body["generationConfig"]["thinkingConfig"]["thinkingLevel"]))
            if len(requests) == 1:
                return httpx.Response(503)
            return _response(_provider_fields())

        settings = _settings(
            gemini_model="gemini-3.6-flash",
            gemini_fallback_model="gemini-3.1-flash-lite",
        )
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await GeminiPostSubmissionVerificationService(
                settings=settings,
                http_client=client,
            ).verify(
                b"passport-image",
                content_type="image/jpeg",
                submitted_fields=_submitted_fields(),
            )

        self.assertEqual(
            requests,
            [
                ("gemini-3.6-flash", "medium"),
                ("gemini-3.1-flash-lite", "minimal"),
            ],
        )
        self.assertEqual(result.provider_status, "verified")
