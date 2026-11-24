"""Actual HTTPX streams enforce limits before buffering provider diagnostics."""

from __future__ import annotations

import gzip
import json

import httpx
import pytest

from app.domain.value_objects.email_ai_analysis import EmailAnalysisProviderStatus
from app.infrastructure.ai.gemini_email_analysis_service import GeminiEmailAnalysisService
from tests.unit.infrastructure.test_gemini_email_analysis_service import (
    _provider_result,
    _request,
)

LIMIT = 192 * 1024


class ProviderBody(httpx.AsyncByteStream):
    def __init__(self, body: bytes, chunk_size: int = 4096):
        self.body = body
        self.chunk_size = chunk_size
        self.bytes_yielded = 0
        self.closed = False

    async def __aiter__(self):
        for start in range(0, len(self.body), self.chunk_size):
            chunk = self.body[start : start + self.chunk_size]
            self.bytes_yielded += len(chunk)
            yield chunk

    async def aclose(self):
        self.closed = True


def _service(client, *, repair=False):
    return GeminiEmailAnalysisService(
        api_key="synthetic-private-api-key",
        model="gemini-test",
        timeout_seconds=4,
        http_client=client,
        repair_invalid_response=repair,
    )


@pytest.mark.parametrize("kind", ["declared", "chunked", "compressed"])
async def test_oversize_provider_stream_is_rejected_before_unbounded_consumption(kind):
    body = ProviderBody(
        gzip.compress(b" " * (LIMIT * 8)) if kind == "compressed" else b" " * (LIMIT * 8)
    )
    headers = {"Content-Length": str(len(body.body))} if kind == "declared" else {}
    if kind == "compressed":
        headers["Content-Encoding"] = "gzip"

    async def handler(request):
        return httpx.Response(200, request=request, headers=headers, stream=body)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await _service(client).analyze(_request())
    assert result.provider_status == EmailAnalysisProviderStatus.INVALID_RESPONSE
    assert result.reason_code == "invalid_provider_response"
    assert result.needs_review and not result.proposals and result.reply_draft is None
    assert body.closed
    assert body.bytes_yielded <= (LIMIT + 16_384 if kind == "chunked" else 0)


@pytest.mark.parametrize(
    "status,expected",
    [
        (429, EmailAnalysisProviderStatus.PROVIDER_UNAVAILABLE),
        (503, EmailAnalysisProviderStatus.PROVIDER_UNAVAILABLE),
        (400, EmailAnalysisProviderStatus.PROVIDER_REJECTED),
    ],
)
async def test_error_status_preserves_classification_without_reading_echoed_private_body(
    status, expected
):
    body = ProviderBody(b"synthetic-passport-and-echoed-api-key" * 1000)

    async def handler(request):
        return httpx.Response(status, request=request, stream=body)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await _service(client).analyze(_request())
    assert result.provider_status == expected
    assert result.needs_review and not result.proposals
    assert body.closed and body.bytes_yielded == 0
    assert "synthetic-passport" not in result.model_dump_json()


async def test_redirect_is_not_followed_even_with_injected_client_default():
    hosts = []

    async def handler(request):
        hosts.append(request.url.host)
        if len(hosts) == 1:
            return httpx.Response(
                307, headers={"location": "https://other.example.test/collect"}, request=request
            )
        return httpx.Response(200, json={})

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), follow_redirects=True
    ) as client:
        result = await _service(client).analyze(_request())
    assert hosts == ["generativelanguage.googleapis.com"]
    assert result.provider_status == EmailAnalysisProviderStatus.PROVIDER_REJECTED


async def test_rejected_stream_gets_exactly_one_repair_then_valid_original_result():
    streams = []

    async def handler(request):
        if not streams:
            body = ProviderBody(b" " * (LIMIT * 8))
        else:
            body = ProviderBody(
                json.dumps(
                    {
                        "candidates": [
                            {"content": {"parts": [{"text": json.dumps(_provider_result())}]}}
                        ]
                    }
                ).encode()
            )
        streams.append(body)
        return httpx.Response(200, request=request, stream=body)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await _service(client, repair=True).analyze(_request())
    assert result.provider_status == EmailAnalysisProviderStatus.ANALYZED
    assert result.repair_attempted and len(streams) == 2
    assert streams[0].bytes_yielded <= LIMIT + 16_384
    assert all(body.closed for body in streams)
    assert result.proposals[0].target_alias == "group_1"
