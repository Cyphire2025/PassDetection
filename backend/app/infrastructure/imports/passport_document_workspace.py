"""Own canonical passport images and their request-lifetime spools."""

from __future__ import annotations

import tempfile
from dataclasses import dataclass, field
from typing import IO

from app.infrastructure.imports.passport_document_streams import (
    PassportDocumentStagingError,
    _read_exact_stream,
)
from app.infrastructure.security.upload_validator import ValidatedUpload

MAX_STAGED_CANONICAL_BYTES = 256 * 1024 * 1024

PASSPORT_DOCUMENT_SPOOL_MEMORY_BYTES = 64 * 1024


@dataclass(frozen=True, slots=True)
class PassportDocumentUploadSource:
    """One seekable framework upload plus its measured, authoritative size."""

    filename: str
    stream: IO[bytes]
    size_bytes: int
    declared_content_type: str | None


@dataclass(slots=True)
class StagedValidatedUpload:
    """Validated canonical image backed by an auto-deleting binary spool."""

    content_type: str
    filename: str
    width: int
    height: int
    format: str
    size_bytes: int
    _stream: IO[bytes] = field(repr=False)

    def read_content(self) -> bytes:
        """Read exactly the staged length and fail closed on truncation or growth."""
        return _read_exact_stream(
            self._stream,
            expected_bytes=self.size_bytes,
            maximum_bytes=self.size_bytes,
            label="Staged passport image",
        )


@dataclass(frozen=True, slots=True)
class PassportDocumentFile:
    filename: str
    staff_code: str
    document_type: str
    upload: StagedValidatedUpload


@dataclass(frozen=True, slots=True)
class RejectedPassportDocument:
    filename: str
    reason: str


class PassportDocumentImportWorkspace:
    """Own every canonical spool and close it deterministically after the request."""

    def __init__(self) -> None:
        self._streams: list[IO[bytes]] = []
        self._staged_bytes = 0
        self._closed = False

    def __enter__(self) -> PassportDocumentImportWorkspace:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    @property
    def staged_bytes(self) -> int:
        return self._staged_bytes

    def stage(self, upload: ValidatedUpload) -> StagedValidatedUpload:
        if self._closed:
            raise PassportDocumentStagingError("Passport import workspace is closed")
        next_total = self._staged_bytes + len(upload.content)
        if next_total > MAX_STAGED_CANONICAL_BYTES:
            raise PassportDocumentStagingError(
                "Validated passport images exceed the bounded staging limit; split the import into smaller batches"
            )
        stream = tempfile.SpooledTemporaryFile(
            max_size=PASSPORT_DOCUMENT_SPOOL_MEMORY_BYTES, mode="w+b"
        )
        try:
            written = stream.write(upload.content)
            if written != len(upload.content):
                raise PassportDocumentStagingError(
                    "Could not stage the complete validated passport image"
                )
            stream.seek(0)
        except Exception:
            stream.close()
            raise
        self._streams.append(stream)
        self._staged_bytes = next_total
        return StagedValidatedUpload(
            content_type=upload.content_type,
            filename=upload.filename,
            width=upload.width,
            height=upload.height,
            format=upload.format,
            size_bytes=len(upload.content),
            _stream=stream,
        )

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        first_error: Exception | None = None
        for stream in self._streams:
            try:
                stream.close()
            except Exception as exc:
                if first_error is None:
                    first_error = exc
        self._streams.clear()
        self._staged_bytes = 0
        if first_error is not None:
            raise first_error
