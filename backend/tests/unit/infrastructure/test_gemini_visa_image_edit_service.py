from __future__ import annotations

import asyncio
import base64
import io
import json
from types import SimpleNamespace
from unittest.mock import patch

import httpx
import pytest
from PIL import Image
from pydantic import SecretStr

from app.infrastructure.ai.gemini_visa_image_edit_service import (
    GeminiVisaImageEditProviderRejected,
    GeminiVisaImageEditProviderUnavailable,
    GeminiVisaImageEditRejected,
    GeminiVisaImageEditService,
)


def _jpeg() -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (160, 220), "white").save(output, format="JPEG", quality=90)
    return output.getvalue()


def _settings(**overrides: object) -> SimpleNamespace:
    values = dict(
        gemini_image_edit_model="gemini-image-model",
        gemini_image_edit_timeout_seconds=300.0,
        google_api_key=SecretStr("test-key"),
        upload_max_file_size_bytes=5 * 1024 * 1024,
        gemini_model="gemini-verifier",
        gemini_fallback_model="gemini-verifier-fallback",
        gemini_api_base_url="https://generativelanguage.googleapis.com/v1beta",
        gemini_timeout_seconds=30,
        gemini_max_retries=1,
        gemini_retry_max_attempts=3,
    )
    values.update(overrides)
    return SimpleNamespace(**values)


def _image_response(content: bytes) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {
                                "inlineData": {
                                    "mimeType": "image/jpeg",
                                    "data": base64.b64encode(content).decode("ascii"),
                                }
                            }
                        ]
                    }
                }
            ]
        },
    )


def _verdict_response(
    *,
    same_identity: bool = True,
    presentation_only: bool = True,
    artifact_free: bool = True,
    confidence: float = 0.99,
) -> httpx.Response:
    verdict = json.dumps(
        {
            "same_identity": same_identity,
            "presentation_only": presentation_only,
            "artifact_free": artifact_free,
            "confidence": confidence,
        }
    )
    return httpx.Response(
        200,
        json={"candidates": [{"content": {"parts": [{"text": verdict}]}}]},
    )


@pytest.mark.asyncio
async def test_service_generates_then_verifies_identity_before_returning_image() -> None:
    source = _jpeg()
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if "gemini-image-model" in request.url.path:
            return httpx.Response(
                200,
                json={
                    "candidates": [
                        {
                            "content": {
                                "parts": [
                                    {
                                        "inlineData": {
                                            "mimeType": "image/jpeg",
                                            "data": base64.b64encode(source).decode("ascii"),
                                        }
                                    }
                                ]
                            }
                        }
                    ]
                },
            )
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {
                                    "text": (
                                        '{"same_identity":true,"presentation_only":true,'
                                        '"artifact_free":true,"confidence":0.99}'
                                    )
                                }
                            ]
                        }
                    }
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = GeminiVisaImageEditService(  # type: ignore[arg-type]
            settings=_settings(),
            http_client=client,
        )
        with patch(
            "app.infrastructure.imaging.passport_image_cropper.get_settings",
            return_value=SimpleNamespace(
                upload_max_file_size_bytes=5 * 1024 * 1024,
                upload_max_pixels=24_000_000,
            ),
        ):
            result = await service.edit(
                source,
                prompt="Make the existing white background even and balance exposure",
            )

    assert len(requests) == 2
    assert "gemini-image-model" in requests[0].url.path
    assert "gemini-verifier" in requests[1].url.path
    assert result.content_type == "image/jpeg"
    with Image.open(io.BytesIO(result.content)) as generated:
        assert generated.size == (160, 220)
        assert generated.getexif() == {}


@pytest.mark.asyncio
async def test_service_rejects_identity_or_biometric_change_prompts_before_api_call() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(500)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = GeminiVisaImageEditService(  # type: ignore[arg-type]
            settings=_settings(),
            http_client=client,
        )
        with pytest.raises(GeminiVisaImageEditRejected, match="cannot change identity"):
            await service.edit(_jpeg(), prompt="Change the face to a different person")

    assert calls == 0


@pytest.mark.asyncio
async def test_verifier_503_retries_once_with_fallback_and_same_candidate() -> None:
    source = _jpeg()
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if "gemini-image-model" in request.url.path:
            return _image_response(source)
        if "gemini-verifier-fallback" in request.url.path:
            return _verdict_response()
        return httpx.Response(503, headers={"Retry-After": "0"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = GeminiVisaImageEditService(  # type: ignore[arg-type]
            settings=_settings(),
            http_client=client,
        )
        with patch(
            "app.infrastructure.imaging.passport_image_cropper.get_settings",
            return_value=SimpleNamespace(
                upload_max_file_size_bytes=5 * 1024 * 1024,
                upload_max_pixels=24_000_000,
            ),
        ):
            result = await service.edit(
                source,
                prompt="Make the background plain white and balance exposure",
            )

    assert result.content_type == "image/jpeg"
    assert [request.url.path.split("/models/")[1].split(":")[0] for request in requests] == [
        "gemini-image-model",
        "gemini-verifier",
        "gemini-verifier-fallback",
    ]
    primary_payload = json.loads(requests[1].content)
    fallback_payload = json.loads(requests[2].content)
    assert primary_payload == fallback_payload
    assert primary_payload["contents"][0]["parts"][3]["inlineData"]["data"]


@pytest.mark.asyncio
async def test_gemini_36_verifier_uses_medium_and_older_fallback_uses_minimal() -> None:
    source = _jpeg()
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if "gemini-3-pro-image" in request.url.path:
            return _image_response(source)
        if "gemini-3.1-flash-lite" in request.url.path:
            return _verdict_response()
        return httpx.Response(503, headers={"Retry-After": "0"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = GeminiVisaImageEditService(  # type: ignore[arg-type]
            settings=_settings(
                gemini_image_edit_model="gemini-3-pro-image",
                gemini_model="gemini-3.6-flash",
                gemini_fallback_model="gemini-3.1-flash-lite",
            ),
            http_client=client,
        )
        with patch(
            "app.infrastructure.imaging.passport_image_cropper.get_settings",
            return_value=SimpleNamespace(
                upload_max_file_size_bytes=5 * 1024 * 1024,
                upload_max_pixels=24_000_000,
            ),
        ):
            result = await service.edit(
                source,
                prompt="Make the background plain white and balance exposure",
            )

    assert result.model == "gemini-3-pro-image"
    assert len(requests) == 3
    primary_payload = json.loads(requests[1].content)
    fallback_payload = json.loads(requests[2].content)
    assert primary_payload["generationConfig"]["thinkingConfig"] == {"thinkingLevel": "medium"}
    assert fallback_payload["generationConfig"]["thinkingConfig"] == {"thinkingLevel": "minimal"}


@pytest.mark.asyncio
async def test_permanent_verifier_4xx_is_not_retried() -> None:
    source = _jpeg()
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if "gemini-image-model" in request.url.path:
            return _image_response(source)
        return httpx.Response(400)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = GeminiVisaImageEditService(  # type: ignore[arg-type]
            settings=_settings(),
            http_client=client,
        )
        with (
            patch(
                "app.infrastructure.imaging.passport_image_cropper.get_settings",
                return_value=SimpleNamespace(
                    upload_max_file_size_bytes=5 * 1024 * 1024,
                    upload_max_pixels=24_000_000,
                ),
            ),
            pytest.raises(GeminiVisaImageEditProviderRejected),
        ):
            await service.edit(source, prompt="Make the background plain white")

    assert len(requests) == 2


@pytest.mark.asyncio
async def test_exhausted_verifier_503_is_provider_unavailable() -> None:
    source = _jpeg()
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if "gemini-image-model" in request.url.path:
            return _image_response(source)
        return httpx.Response(503, headers={"Retry-After": "0"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = GeminiVisaImageEditService(  # type: ignore[arg-type]
            settings=_settings(),
            http_client=client,
        )
        with (
            patch(
                "app.infrastructure.imaging.passport_image_cropper.get_settings",
                return_value=SimpleNamespace(
                    upload_max_file_size_bytes=5 * 1024 * 1024,
                    upload_max_pixels=24_000_000,
                ),
            ),
            pytest.raises(
                GeminiVisaImageEditProviderUnavailable,
                match="identity verification is temporarily unavailable",
            ),
        ):
            await service.edit(source, prompt="Make the background plain white")

    assert len(requests) == 3


@pytest.mark.asyncio
async def test_negative_identity_verdict_never_uses_fallback() -> None:
    source = _jpeg()
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if "gemini-image-model" in request.url.path:
            return _image_response(source)
        return _verdict_response(same_identity=False, confidence=0.99)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = GeminiVisaImageEditService(  # type: ignore[arg-type]
            settings=_settings(),
            http_client=client,
        )
        with (
            patch(
                "app.infrastructure.imaging.passport_image_cropper.get_settings",
                return_value=SimpleNamespace(
                    upload_max_file_size_bytes=5 * 1024 * 1024,
                    upload_max_pixels=24_000_000,
                ),
            ),
            pytest.raises(GeminiVisaImageEditRejected, match="identity-preserving"),
        ):
            await service.edit(source, prompt="Make the background plain white")

    assert len(requests) == 2


@pytest.mark.asyncio
async def test_waiting_for_ai_capacity_is_bounded_without_leaking_a_permit() -> None:
    source = _jpeg()
    calls = 0
    saturated = asyncio.Semaphore(0)

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(500)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = GeminiVisaImageEditService(  # type: ignore[arg-type]
            settings=_settings(),
            http_client=client,
        )
        with (
            patch.object(GeminiVisaImageEditService, "_semaphore", saturated),
            patch.object(service, "_operation_timeout_seconds", return_value=0.02),
            patch(
                "app.infrastructure.imaging.passport_image_cropper.get_settings",
                return_value=SimpleNamespace(
                    upload_max_file_size_bytes=5 * 1024 * 1024,
                    upload_max_pixels=24_000_000,
                ),
            ),
            pytest.raises(GeminiVisaImageEditProviderUnavailable, match="timed out"),
        ):
            await service.edit(source, prompt="Make the background plain white")

    assert calls == 0
    saturated.release()
    await asyncio.wait_for(saturated.acquire(), timeout=0.1)
    assert saturated.locked()


@pytest.mark.parametrize("confidence", [True, float("nan"), float("inf"), 1.01])
@pytest.mark.asyncio
async def test_invalid_verifier_confidence_is_a_provider_failure(
    confidence: float | bool,
) -> None:
    source = _jpeg()

    def handler(request: httpx.Request) -> httpx.Response:
        if "gemini-image-model" in request.url.path:
            return _image_response(source)
        return _verdict_response(confidence=confidence)  # type: ignore[arg-type]

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = GeminiVisaImageEditService(  # type: ignore[arg-type]
            settings=_settings(),
            http_client=client,
        )
        with (
            patch(
                "app.infrastructure.imaging.passport_image_cropper.get_settings",
                return_value=SimpleNamespace(
                    upload_max_file_size_bytes=5 * 1024 * 1024,
                    upload_max_pixels=24_000_000,
                ),
            ),
            pytest.raises(GeminiVisaImageEditProviderRejected, match="confidence"),
        ):
            await service.edit(source, prompt="Make the background plain white")


@pytest.mark.asyncio
async def test_malformed_verifier_json_is_a_provider_failure() -> None:
    source = _jpeg()

    def handler(request: httpx.Request) -> httpx.Response:
        if "gemini-image-model" in request.url.path:
            return _image_response(source)
        return httpx.Response(
            200,
            json={"candidates": [{"content": {"parts": [{"text": "not-json"}]}}]},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = GeminiVisaImageEditService(  # type: ignore[arg-type]
            settings=_settings(),
            http_client=client,
        )
        with (
            patch(
                "app.infrastructure.imaging.passport_image_cropper.get_settings",
                return_value=SimpleNamespace(
                    upload_max_file_size_bytes=5 * 1024 * 1024,
                    upload_max_pixels=24_000_000,
                ),
            ),
            pytest.raises(GeminiVisaImageEditProviderRejected, match="unreadable response"),
        ):
            await service.edit(source, prompt="Make the background plain white")


@pytest.mark.asyncio
async def test_unreadable_generated_image_is_a_provider_failure() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert "gemini-image-model" in request.url.path
        return _image_response(b"not-an-image")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = GeminiVisaImageEditService(  # type: ignore[arg-type]
            settings=_settings(),
            http_client=client,
        )
        with (
            patch(
                "app.infrastructure.imaging.passport_image_cropper.get_settings",
                return_value=SimpleNamespace(
                    upload_max_file_size_bytes=5 * 1024 * 1024,
                    upload_max_pixels=24_000_000,
                ),
            ),
            pytest.raises(GeminiVisaImageEditProviderRejected, match="unreadable edited image"),
        ):
            await service.edit(_jpeg(), prompt="Make the background plain white")
