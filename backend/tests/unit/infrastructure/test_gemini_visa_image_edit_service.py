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
from pydantic import SecretStr, ValidationError

from app.core.config.settings import Settings
from app.infrastructure.ai.gemini_visa_image_edit_service import (
    GeminiVisaImageEditError,
    GeminiVisaImageEditProviderRejected,
    GeminiVisaImageEditProviderUnavailable,
    GeminiVisaImageEditRejected,
    GeminiVisaImageEditService,
)

_PRIMARY_MODEL = "gemini-3.1-flash-image"
_FALLBACK_MODEL = "gemini-3-pro-image"


def _jpeg() -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (160, 220), "white").save(output, format="JPEG", quality=90)
    return output.getvalue()


def _settings(**overrides: object) -> SimpleNamespace:
    values = dict(
        gemini_image_edit_model=_PRIMARY_MODEL,
        gemini_image_edit_fallback_model=_FALLBACK_MODEL,
        gemini_image_edit_attempt_timeout_seconds=120.0,
        gemini_image_edit_timeout_seconds=300.0,
        google_api_key=SecretStr("test-key"),
        upload_max_file_size_bytes=5 * 1024 * 1024,
        gemini_api_base_url="https://generativelanguage.googleapis.com/v1beta",
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


def _no_candidates_response() -> httpx.Response:
    return httpx.Response(200, json={"candidates": []})


def test_image_edit_settings_have_ordered_validated_defaults() -> None:
    assert Settings.model_fields["gemini_image_edit_model"].default == _PRIMARY_MODEL
    assert Settings.model_fields["gemini_image_edit_fallback_model"].default == _FALLBACK_MODEL
    assert Settings.model_fields["gemini_image_edit_attempt_timeout_seconds"].default == 120.0

    with pytest.raises(ValidationError, match="invalid characters"):
        Settings(
            app_secret_key="unit-test-secret",
            gemini_image_edit_fallback_model="invalid/model",
            _env_file=None,
        )


@pytest.mark.asyncio
async def test_service_returns_generated_image_without_a_verification_request() -> None:
    source = _jpeg()
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert _PRIMARY_MODEL in request.url.path
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
    assert _PRIMARY_MODEL in requests[0].url.path
    assert _FALLBACK_MODEL not in requests[0].url.path
    assert result.model == _PRIMARY_MODEL
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
        assert _PRIMARY_MODEL in request.url.path
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
async def test_generation_503_uses_the_fallback_model_in_order() -> None:
    source = _jpeg()
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) == 1:
            assert _PRIMARY_MODEL in request.url.path
            return httpx.Response(503)
        assert _FALLBACK_MODEL in request.url.path
        return _image_response(source)

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
            patch(
                "app.infrastructure.ai.gemini_visa_image_edit_service.logger"
            ) as mock_logger,
        ):
            result = await service.edit(
                source,
                prompt="Make the background plain white and balance exposure",
            )

    assert result.content_type == "image/jpeg"
    assert result.model == _FALLBACK_MODEL
    assert len(requests) == 2
    assert requests[0].url.path != requests[1].url.path
    assert json.loads(requests[0].content) == json.loads(requests[1].content)
    failure_log = mock_logger.warning.call_args_list[0]
    assert failure_log.args == ("visa_ai_image_edit_attempt_completed",)
    assert failure_log.kwargs["model"] == _PRIMARY_MODEL
    assert failure_log.kwargs["attempt"] == 1
    assert failure_log.kwargs["outcome"] == "provider_unavailable"
    assert failure_log.kwargs["fallback"] is True
    log_output = repr(mock_logger.method_calls)
    assert "Make the background" not in log_output
    assert "test-key" not in log_output
    assert base64.b64encode(source).decode("ascii") not in log_output


@pytest.mark.asyncio
async def test_no_usable_primary_result_uses_the_fallback_model() -> None:
    source = _jpeg()
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if _PRIMARY_MODEL in request.url.path:
            return _no_candidates_response()
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
                prompt="Make the background plain white",
            )

    assert result.model == _FALLBACK_MODEL
    assert len(requests) == 2
    assert _PRIMARY_MODEL in requests[0].url.path
    assert _FALLBACK_MODEL in requests[1].url.path


@pytest.mark.asyncio
async def test_primary_provider_timeout_uses_the_fallback_model() -> None:
    source = _jpeg()
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if _PRIMARY_MODEL in request.url.path:
            raise httpx.ReadTimeout("primary timed out", request=request)
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
                prompt="Make the background plain white",
            )

    assert result.model == _FALLBACK_MODEL
    assert len(requests) == 2
    assert _PRIMARY_MODEL in requests[0].url.path
    assert _FALLBACK_MODEL in requests[1].url.path


@pytest.mark.asyncio
async def test_both_models_without_a_usable_result_return_the_final_error() -> None:
    source = _jpeg()
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return _no_candidates_response()

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
            pytest.raises(GeminiVisaImageEditError, match="no usable result"),
        ):
            await service.edit(
                source,
                prompt="Make the background plain white",
            )

    assert len(requests) == 2
    assert _PRIMARY_MODEL in requests[0].url.path
    assert _FALLBACK_MODEL in requests[1].url.path


@pytest.mark.asyncio
async def test_model_specific_bad_request_uses_the_fallback_model() -> None:
    source = _jpeg()
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if _PRIMARY_MODEL in request.url.path:
            return httpx.Response(400)
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
                prompt="Make the background plain white",
            )

    assert result.model == _FALLBACK_MODEL
    assert len(requests) == 2


@pytest.mark.asyncio
async def test_permanent_authentication_4xx_does_not_call_the_fallback() -> None:
    source = _jpeg()
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert _PRIMARY_MODEL in request.url.path
        return httpx.Response(401)

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
        return httpx.Response(503)

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
    assert _PRIMARY_MODEL in requests[0].url.path
    assert _FALLBACK_MODEL in requests[1].url.path


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
async def test_unreadable_primary_generated_image_uses_fallback() -> None:
    source = _jpeg()
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if _PRIMARY_MODEL in request.url.path:
            return _image_response(b"not-an-image")
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
                prompt="Make the background plain white",
            )

    assert result.model == _FALLBACK_MODEL
    assert len(requests) == 2
