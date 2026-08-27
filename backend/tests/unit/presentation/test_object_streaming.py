from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from fastapi import HTTPException

from app.infrastructure.storage.minio_repository import ObjectIntegrityMetadata
from app.presentation.api.v1.object_streaming import (
    private_object_streaming_response,
)


class _Storage:
    def __init__(self, content: bytes) -> None:
        self.content = content
        self.stream_calls: list[tuple[str, int, int]] = []

    async def stat_file(self, _key: str) -> ObjectIntegrityMetadata:
        return ObjectIntegrityMetadata(
            size_bytes=len(self.content),
            checksum_sha256=None,
            content_type="image/jpeg",
        )

    async def stream_file(
        self,
        key: str,
        *,
        start: int,
        expected_bytes: int,
        chunk_size: int = 64 * 1024,
    ) -> AsyncIterator[bytes]:
        del chunk_size
        self.stream_calls.append((key, start, expected_bytes))
        yield self.content[start : start + expected_bytes]


async def _body(response: object) -> bytes:
    chunks = []
    async for chunk in response.body_iterator:  # type: ignore[attr-defined]
        chunks.append(bytes(chunk))
    return b"".join(chunks)


@pytest.mark.asyncio
async def test_full_object_is_streamed_without_materializing_it_first() -> None:
    storage = _Storage(b"0123456789")
    response = await private_object_streaming_response(
        storage=storage,  # type: ignore[arg-type]
        key="private/object.jpg",
        media_type="image/jpeg",
        content_disposition='inline; filename="passport.jpg"',
        range_header=None,
    )

    assert response.status_code == 200
    assert response.headers["content-length"] == "10"
    assert response.headers["accept-ranges"] == "bytes"
    assert await _body(response) == b"0123456789"
    assert storage.stream_calls == [("private/object.jpg", 0, 10)]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("range_header", "expected", "content_range"),
    [
        ("bytes=2-5", b"2345", "bytes 2-5/10"),
        ("bytes=7-", b"789", "bytes 7-9/10"),
        ("bytes=-3", b"789", "bytes 7-9/10"),
        ("bytes=8-99", b"89", "bytes 8-9/10"),
    ],
)
async def test_single_range_support_is_exact_and_resume_safe(
    range_header: str,
    expected: bytes,
    content_range: str,
) -> None:
    response = await private_object_streaming_response(
        storage=_Storage(b"0123456789"),  # type: ignore[arg-type]
        key="private/object.jpg",
        media_type="image/jpeg",
        content_disposition='inline; filename="passport.jpg"',
        range_header=range_header,
    )

    assert response.status_code == 206
    assert response.headers["content-range"] == content_range
    assert response.headers["content-length"] == str(len(expected))
    assert await _body(response) == expected


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "range_header",
    ["bytes=", "bytes=10-", "bytes=5-2", "items=0-1", "bytes=0-1,4-5"],
)
async def test_invalid_or_multi_range_request_fails_with_416(
    range_header: str,
) -> None:
    with pytest.raises(HTTPException) as rejected:
        await private_object_streaming_response(
            storage=_Storage(b"0123456789"),  # type: ignore[arg-type]
            key="private/object.jpg",
            media_type="image/jpeg",
            content_disposition='inline; filename="passport.jpg"',
            range_header=range_header,
        )

    assert rejected.value.status_code == 416
    assert rejected.value.headers == {"Content-Range": "bytes */10"}
