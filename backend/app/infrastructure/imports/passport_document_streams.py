"""Exact-length bounded reads for request-owned passport streams."""

from __future__ import annotations

from typing import IO

MAX_MEMBER_BYTES = 20 * 1024 * 1024

PASSPORT_DOCUMENT_READ_CHUNK_BYTES = 64 * 1024


class PassportDocumentStagingError(RuntimeError):
    """The bounded request staging contract could not be maintained."""


def _read_exact_stream(
    stream: IO[bytes], *, expected_bytes: int, maximum_bytes: int, label: str
) -> bytes:
    stream.seek(0)
    try:
        return _read_forward_stream_exact(
            stream, expected_bytes=expected_bytes, maximum_bytes=maximum_bytes, label=label
        )
    finally:
        stream.seek(0)


def _read_forward_stream_exact(
    stream: IO[bytes], *, expected_bytes: int, maximum_bytes: int, label: str
) -> bytes:
    if expected_bytes < 0 or expected_bytes > maximum_bytes:
        raise PassportDocumentStagingError(f"{label} exceeds its bounded byte limit")
    chunks: list[bytes] = []
    consumed = 0
    while consumed <= expected_bytes:
        remaining_with_probe = expected_bytes - consumed + 1
        chunk = stream.read(min(PASSPORT_DOCUMENT_READ_CHUNK_BYTES, remaining_with_probe))
        if not chunk:
            break
        consumed += len(chunk)
        if consumed > expected_bytes:
            raise PassportDocumentStagingError(f"{label} exceeded its declared size")
        chunks.append(bytes(chunk))
    if consumed != expected_bytes:
        raise PassportDocumentStagingError(f"{label} ended before its declared size")
    return b"".join(chunks)
