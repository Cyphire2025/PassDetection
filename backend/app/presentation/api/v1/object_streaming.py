"""Private object-storage streaming with bounded single-range support."""

from __future__ import annotations

import re
from typing import NoReturn

from fastapi import HTTPException, status
from fastapi.responses import StreamingResponse

from app.domain.exceptions.exceptions import StorageError
from app.infrastructure.storage.minio_repository import MinioStorageRepository

_SINGLE_RANGE = re.compile(r"^bytes=(\d*)-(\d*)$")


async def private_object_streaming_response(
    *,
    storage: MinioStorageRepository,
    key: str,
    media_type: str,
    content_disposition: str,
    range_header: str | None,
) -> StreamingResponse:
    """Authorize first, then stream exactly one immutable object byte range."""

    try:
        metadata = await storage.stat_file(key)
    except StorageError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=exc.message,
        ) from exc
    if metadata.size_bytes < 1:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The stored document is temporarily unavailable.",
        )

    start, end, partial = _requested_range(
        range_header,
        size_bytes=metadata.size_bytes,
    )
    expected_bytes = end - start + 1
    headers = {
        "Accept-Ranges": "bytes",
        "Cache-Control": "private, no-store",
        "Content-Disposition": content_disposition,
        "Content-Length": str(expected_bytes),
        "X-Content-Type-Options": "nosniff",
    }
    if partial:
        headers["Content-Range"] = (
            f"bytes {start}-{end}/{metadata.size_bytes}"
        )

    return StreamingResponse(
        storage.stream_file(
            key,
            start=start,
            expected_bytes=expected_bytes,
        ),
        status_code=(
            status.HTTP_206_PARTIAL_CONTENT if partial else status.HTTP_200_OK
        ),
        media_type=media_type,
        headers=headers,
    )


def _requested_range(
    value: str | None,
    *,
    size_bytes: int,
) -> tuple[int, int, bool]:
    if value is None:
        return 0, size_bytes - 1, False
    match = _SINGLE_RANGE.fullmatch(value.strip())
    if match is None:
        _raise_unsatisfiable(size_bytes)
    start_text, end_text = match.groups()
    if not start_text and not end_text:
        _raise_unsatisfiable(size_bytes)

    if start_text:
        start = int(start_text)
        if start >= size_bytes:
            _raise_unsatisfiable(size_bytes)
        end = min(int(end_text), size_bytes - 1) if end_text else size_bytes - 1
        if end < start:
            _raise_unsatisfiable(size_bytes)
        return start, end, True

    suffix_bytes = int(end_text)
    if suffix_bytes < 1:
        _raise_unsatisfiable(size_bytes)
    start = max(0, size_bytes - suffix_bytes)
    return start, size_bytes - 1, True


def _raise_unsatisfiable(size_bytes: int) -> NoReturn:
    raise HTTPException(
        status_code=status.HTTP_416_RANGE_NOT_SATISFIABLE,
        detail="The requested byte range is not satisfiable.",
        headers={"Content-Range": f"bytes */{size_bytes}"},
    )


__all__ = ["private_object_streaming_response"]
