"""Bound provider vision responses before JSON parsing or buffering them in full."""

from __future__ import annotations

from typing import Any

import httpx


class VisionResponseRejected(ValueError):
    """A provider response cannot be consumed within the vision contract."""


async def post_bounded_vision_response(
    client: httpx.AsyncClient,
    endpoint: str,
    *,
    headers: dict[str, str],
    payload: dict[str, Any],
    timeout: httpx.Timeout,
    maximum_bytes: int,
) -> httpx.Response:
    """Return only bounded successful content; error handling needs status/headers.

    Callers retain ownership of their complete attempt timeout and retry policy.
    Identity encoding keeps the decoded size limit from admitting a compressed
    response that expands before HTTPX can yield a bounded chunk.
    """

    if maximum_bytes <= 0:
        raise ValueError("Vision response limit must be positive")
    async with client.stream(
        "POST",
        endpoint,
        headers={**headers, "Accept-Encoding": "identity"},
        json=payload,
        timeout=timeout,
        follow_redirects=False,
    ) as response:
        # Provider error bodies may contain echoed input. Neither service needs
        # them for retry/classification, so do not download or retain them.
        if not 200 <= response.status_code < 300:
            return httpx.Response(
                response.status_code,
                headers=response.headers,
                content=b"",
                request=response.request,
            )
        encoding = response.headers.get("Content-Encoding", "identity").strip().lower()
        if encoding not in {"", "identity"}:
            raise VisionResponseRejected("Unsupported vision response encoding")
        try:
            declared_length = int(response.headers.get("Content-Length", ""))
        except ValueError:
            declared_length = None
        if declared_length is not None and declared_length > maximum_bytes:
            raise VisionResponseRejected("Vision response exceeds its byte limit")
        body = bytearray()
        async for chunk in response.aiter_bytes(chunk_size=min(16_384, maximum_bytes + 1)):
            if len(chunk) > maximum_bytes - len(body):
                raise VisionResponseRejected("Vision response exceeds its byte limit")
            body.extend(chunk)
        return httpx.Response(
            response.status_code,
            headers=response.headers,
            content=bytes(body),
            request=response.request,
        )
