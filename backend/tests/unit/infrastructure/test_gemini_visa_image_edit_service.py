from __future__ import annotations

import base64
import io
from types import SimpleNamespace
from unittest.mock import patch

import httpx
import pytest
from PIL import Image
from pydantic import SecretStr

from app.infrastructure.ai.gemini_visa_image_edit_service import (
    GeminiVisaImageEditRejected,
    GeminiVisaImageEditService,
)


def _jpeg() -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (160, 220), "white").save(output, format="JPEG", quality=90)
    return output.getvalue()


def _settings() -> SimpleNamespace:
    return SimpleNamespace(
        gemini_image_edit_model="gemini-image-model",
        google_api_key=SecretStr("test-key"),
        upload_max_file_size_bytes=5 * 1024 * 1024,
        gemini_model="gemini-verifier",
        gemini_api_base_url="https://generativelanguage.googleapis.com/v1beta",
        gemini_timeout_seconds=30,
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
                    "candidates": [{
                        "content": {
                            "parts": [{
                                "inlineData": {
                                    "mimeType": "image/jpeg",
                                    "data": base64.b64encode(source).decode("ascii"),
                                }
                            }]
                        }
                    }]
                },
            )
        return httpx.Response(
            200,
            json={
                "candidates": [{
                    "content": {
                        "parts": [{
                            "text": (
                                '{"same_identity":true,"presentation_only":true,'
                                '"artifact_free":true,"confidence":0.99}'
                            )
                        }]
                    }
                }]
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
