"""Exercise response limits using streamed synthetic HTTP transports."""

from __future__ import annotations

import asyncio

import httpx
import pytest

from app.infrastructure.ai.bounded_vision_http import (
    VisionResponseRejected,
    post_bounded_vision_response,
)


class CountingBody(httpx.AsyncByteStream):
    def __init__(self, chunks: int = 64, *, pause: bool = False) -> None:
        self.chunks = chunks
        self.pause = pause
        self.reads = 0
        self.closed = False

    async def __aiter__(self):
        for _ in range(self.chunks):
            self.reads += 1
            if self.pause:
                await asyncio.sleep(1)
            yield b"x" * 128

    async def aclose(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_size_limit_stops_before_downloading_complete_provider_response() -> None:
    legacy_body, bounded_body = CountingBody(), CountingBody()
    bodies = iter([legacy_body, bounded_body])
    transport = httpx.MockTransport(lambda request: httpx.Response(200, stream=next(bodies)))
    async with httpx.AsyncClient(transport=transport) as client:
        # Reproduce the preceding buffered POST boundary with the same transport.
        legacy = await client.post("https://provider.invalid/vision")
        assert len(legacy.content) == 8192 and legacy_body.reads == 64
        with pytest.raises(VisionResponseRejected):
            await post_bounded_vision_response(
                client,
                "https://provider.invalid/vision",
                headers={},
                payload={},
                timeout=httpx.Timeout(1),
                maximum_bytes=1024,
            )
    assert bounded_body.reads == 9
    assert legacy_body.closed and bounded_body.closed


@pytest.mark.asyncio
async def test_headers_and_error_status_reject_without_consuming_sensitive_body() -> None:
    for status, headers, rejected in [
        (200, {"Content-Length": "99999"}, True),
        (200, {"Content-Encoding": "gzip"}, True),
        (429, {}, False),
        (403, {}, False),
    ]:
        body = CountingBody()
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(status, headers=headers, stream=body),
            )
        ) as client:

            async def post():
                return await post_bounded_vision_response(
                    client,
                    "https://provider.invalid/vision",
                    headers={},
                    payload={},
                    timeout=httpx.Timeout(1),
                    maximum_bytes=1024,
                )

            if rejected:
                with pytest.raises(VisionResponseRejected):
                    await post()
            else:
                response = await post()
                assert response.status_code == status and response.content == b""
        assert body.reads == 0 and body.closed


@pytest.mark.asyncio
async def test_identity_encoding_redirect_boundary_and_exact_limit() -> None:
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/redirect":
            return httpx.Response(302, headers={"Location": "https://unrelated.invalid/secret"})
        return httpx.Response(200, content=b"x" * 1024)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), follow_redirects=True
    ) as client:
        response = await post_bounded_vision_response(
            client,
            "https://provider.invalid/vision",
            headers={"x-goog-api-key": "synthetic"},
            payload={},
            timeout=httpx.Timeout(1),
            maximum_bytes=1024,
        )
        assert len(response.content) == 1024 and response.is_closed
        redirect = await post_bounded_vision_response(
            client,
            "https://provider.invalid/redirect",
            headers={"x-goog-api-key": "synthetic"},
            payload={},
            timeout=httpx.Timeout(1),
            maximum_bytes=1024,
        )
        assert redirect.status_code == 302
    assert len(requests) == 2
    assert all(request.url.host == "provider.invalid" for request in requests)
    assert all(request.headers["Accept-Encoding"] == "identity" for request in requests)


@pytest.mark.asyncio
async def test_attempt_cancellation_closes_provider_stream() -> None:
    body = CountingBody(pause=True)
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, stream=body),
        )
    ) as client:
        with pytest.raises(TimeoutError):
            async with asyncio.timeout(0.01):
                await post_bounded_vision_response(
                    client,
                    "https://provider.invalid/vision",
                    headers={},
                    payload={},
                    timeout=httpx.Timeout(1),
                    maximum_bytes=1024,
                )
    assert body.reads == 1 and body.closed
