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
        gemini_api_base_url="https://generativelanguage.googleapis.com/v1beta",
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


@pytest.mark.asyncio
async def test_service_returns_generated_image_without_a_verification_request() -> None:
    source = _jpeg()
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert "gemini-image-model" in request.url.path
        return _image_response(source)

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

    assert len(requests) == 1
    assert "gemini-image-model" in requests[0].url.path
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
        with pytest.raises(GeminiVisaImageEditRejected, match="cannot replace the person"):
            await service.edit(_jpeg(), prompt="Change the face to a different person")

    assert calls == 0


@pytest.mark.asyncio
async def test_service_allows_arbitrary_presentation_prompt_wording() -> None:
    source = _jpeg()
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert "gemini-image-model" in request.url.path
        return _image_response(source)

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
                prompt=(
                    "Remove the glasses, tidy the hair, use formal clothing, "
                    "and make this look like a studio Visa portrait"
                ),
            )

    assert result.content_type == "image/jpeg"
    assert len(requests) == 1
    generation_payload = json.loads(requests[0].content)
    assert generation_payload["contents"][0]["parts"][0]["text"].startswith(
        "Remove the glasses"
    )


@pytest.mark.asyncio
async def test_generation_503_retries_once_with_the_image_model() -> None:
    source = _jpeg()
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert "gemini-image-model" in request.url.path
        if len(requests) == 1:
            return httpx.Response(503, headers={"Retry-After": "0"})
        return _image_response(source)

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
    assert len(requests) == 2
    assert requests[0].url.path == requests[1].url.path
    assert json.loads(requests[0].content) == json.loads(requests[1].content)


@pytest.mark.asyncio
async def test_permanent_generation_4xx_is_not_retried() -> None:
    source = _jpeg()
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert "gemini-image-model" in request.url.path
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

    assert len(requests) == 1


@pytest.mark.asyncio
async def test_exhausted_generation_503_is_provider_unavailable() -> None:
    source = _jpeg()
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert "gemini-image-model" in request.url.path
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
                match="generation is temporarily unavailable",
            ),
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
