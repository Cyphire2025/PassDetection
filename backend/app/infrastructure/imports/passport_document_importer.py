"""Bounded, filename-driven import of staff passport document bundles.

Upload bodies remain in Starlette's spooled files. The importer reads one
archive member at a time, validates and canonicalizes that image, then moves
the canonical bytes into an auto-deleting spool owned by the request. This
keeps peak Python memory proportional to one image instead of the whole ZIP.
"""

from __future__ import annotations

import re
import stat
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import IO

from app.domain.exceptions.exceptions import ImageValidationError
from app.infrastructure.security.upload_validator import UploadValidator, ValidatedUpload

MAX_ARCHIVES = 8
MAX_DIRECT_FILES = 500
MAX_ARCHIVE_BYTES = 128 * 1024 * 1024
MAX_TOTAL_SOURCE_BYTES = 256 * 1024 * 1024
MAX_MEMBERS = 5_000
MAX_MEMBER_BYTES = 20 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 512 * 1024 * 1024
MAX_STAGED_CANONICAL_BYTES = 256 * 1024 * 1024
MAX_COMPRESSION_RATIO = 100
PASSPORT_DOCUMENT_READ_CHUNK_BYTES = 64 * 1024
PASSPORT_DOCUMENT_SPOOL_MEMORY_BYTES = 64 * 1024
_NAME_PATTERN = (
    r"^STF_(?P<staff_code>[A-Za-z0-9-]{1,80})_"
    r"(?P<document_type>PHOTO|FRONT|BACK)\."
    r"(?P<extension>jpe?g|png|webp)$"
)


class PassportDocumentStagingError(RuntimeError):
    """The bounded request staging contract could not be maintained."""


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
                "Validated passport images exceed the bounded staging limit; "
                "split the import into smaller batches"
            )
        stream = tempfile.SpooledTemporaryFile(
            max_size=PASSPORT_DOCUMENT_SPOOL_MEMORY_BYTES,
            mode="w+b",
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
        for stream in self._streams:
            stream.close()
        self._streams.clear()
        self._staged_bytes = 0


@dataclass(slots=True)
class _ImportBudget:
    uncompressed_bytes: int = 0


class PassportDocumentImporter:
    """Expand safe ZIPs and validate ``STF_<staffcode>_<kind>`` images."""

    def __init__(self, validator: UploadValidator | None = None) -> None:
        self._validator = validator or UploadValidator()

    def collect(
        self,
        sources: list[PassportDocumentUploadSource],
        *,
        workspace: PassportDocumentImportWorkspace,
        allowed_staff_codes: set[str] | None = None,
    ) -> tuple[list[PassportDocumentFile], list[RejectedPassportDocument]]:
        accepted: list[PassportDocumentFile] = []
        rejected: list[RejectedPassportDocument] = []
        if not sources:
            return accepted, rejected
        if any(source.size_bytes < 0 for source in sources):
            return accepted, [RejectedPassportDocument("upload", "Upload size is invalid")]
        total_source_bytes = sum(source.size_bytes for source in sources)
        if total_source_bytes > MAX_TOTAL_SOURCE_BYTES:
            return accepted, [
                RejectedPassportDocument(
                    "upload",
                    "Upload exceeds the 256 MB request staging limit; split it into smaller batches",
                )
            ]

        archive_count = 0
        direct_count = 0
        budget = _ImportBudget()
        for source in sources:
            if source.size_bytes > MAX_ARCHIVE_BYTES:
                rejected.append(
                    RejectedPassportDocument(
                        source.filename,
                        "File exceeds the 128 MB bounded import limit",
                    )
                )
                continue
            try:
                is_archive = self._is_zip(source)
            except (OSError, ValueError):
                rejected.append(
                    RejectedPassportDocument(source.filename, "Uploaded file could not be read")
                )
                continue

            if is_archive:
                archive_count += 1
                if archive_count > MAX_ARCHIVES:
                    rejected.append(
                        RejectedPassportDocument(
                            source.filename,
                            f"Upload at most {MAX_ARCHIVES} ZIP archives at a time",
                        )
                    )
                    continue
                accepted_part, rejected_part = self._collect_zip(
                    source,
                    workspace=workspace,
                    budget=budget,
                    allowed_staff_codes=allowed_staff_codes,
                )
            else:
                direct_count += 1
                if direct_count > MAX_DIRECT_FILES:
                    rejected.append(
                        RejectedPassportDocument(
                            source.filename,
                            f"Upload at most {MAX_DIRECT_FILES} direct image files at a time",
                        )
                    )
                    continue
                accepted_part, rejected_part = self._collect_direct(
                    source,
                    workspace=workspace,
                    allowed_staff_codes=allowed_staff_codes,
                )
            accepted.extend(accepted_part)
            rejected.extend(rejected_part)

        seen: set[tuple[str, str]] = set()
        unique: list[PassportDocumentFile] = []
        for item in accepted:
            key = (item.staff_code.casefold(), item.document_type)
            if key in seen:
                rejected.append(
                    RejectedPassportDocument(
                        item.filename,
                        "Duplicate document type for this staff code",
                    )
                )
            else:
                seen.add(key)
                unique.append(item)
        return unique, rejected

    def _is_zip(self, source: PassportDocumentUploadSource) -> bool:
        source.stream.seek(0)
        try:
            return zipfile.is_zipfile(source.stream)
        finally:
            source.stream.seek(0)

    def _collect_zip(
        self,
        source: PassportDocumentUploadSource,
        *,
        workspace: PassportDocumentImportWorkspace,
        budget: _ImportBudget,
        allowed_staff_codes: set[str] | None,
    ) -> tuple[list[PassportDocumentFile], list[RejectedPassportDocument]]:
        accepted: list[PassportDocumentFile] = []
        rejected: list[RejectedPassportDocument] = []
        try:
            source.stream.seek(0)
            with zipfile.ZipFile(source.stream) as archive:
                members = archive.infolist()
                if len(members) > MAX_MEMBERS:
                    return accepted, [
                        RejectedPassportDocument(
                            source.filename,
                            f"ZIP contains more than {MAX_MEMBERS} entries",
                        )
                    ]
                if any(info.flag_bits & 0x1 for info in members):
                    return accepted, [
                        RejectedPassportDocument(
                            source.filename,
                            "Encrypted ZIP archives are not allowed",
                        )
                    ]
                for info in members:
                    path = PurePosixPath(info.filename.replace("\\", "/"))
                    if not info.filename or path.is_absolute() or ".." in path.parts:
                        rejected.append(
                            RejectedPassportDocument(
                                info.filename or source.filename,
                                "Unsafe ZIP path",
                            )
                        )
                        continue
                    if info.is_dir():
                        continue
                    if stat.S_ISLNK(info.external_attr >> 16):
                        rejected.append(
                            RejectedPassportDocument(
                                info.filename,
                                "ZIP symlink entries are not allowed",
                            )
                        )
                        continue
                    if info.file_size > MAX_MEMBER_BYTES:
                        rejected.append(
                            RejectedPassportDocument(
                                info.filename,
                                "Image exceeds the 20 MB per-file limit",
                            )
                        )
                        continue
                    budget.uncompressed_bytes += info.file_size
                    if budget.uncompressed_bytes > MAX_UNCOMPRESSED_BYTES:
                        return accepted, rejected + [
                            RejectedPassportDocument(
                                source.filename,
                                "ZIP imports exceed the 512 MB extracted-size staging limit",
                            )
                        ]
                    if info.file_size > 0 and info.compress_size <= 0:
                        rejected.append(
                            RejectedPassportDocument(
                                info.filename,
                                "Suspicious ZIP compression metadata",
                            )
                        )
                        continue
                    if (
                        info.compress_size > 0
                        and info.file_size / info.compress_size > MAX_COMPRESSION_RATIO
                    ):
                        rejected.append(
                            RejectedPassportDocument(
                                info.filename,
                                "Suspicious ZIP compression ratio",
                            )
                        )
                        continue
                    basename = path.name
                    parsed = self._parse_name(basename)
                    if parsed is None:
                        rejected.append(self._invalid_filename(info.filename))
                        continue
                    if allowed_staff_codes is not None and parsed[0] not in allowed_staff_codes:
                        rejected.append(
                            RejectedPassportDocument(
                                info.filename,
                                "Staff code was not found in this group",
                            )
                        )
                        continue
                    with archive.open(info) as member:
                        member_content = _read_forward_stream_exact(
                            member,
                            expected_bytes=info.file_size,
                            maximum_bytes=MAX_MEMBER_BYTES,
                            label="ZIP member",
                        )
                    accepted_part, rejected_part = self._validate_one(
                        filename=basename,
                        content=member_content,
                        declared_type=None,
                        workspace=workspace,
                        allowed_staff_codes=allowed_staff_codes,
                    )
                    accepted.extend(accepted_part)
                    rejected.extend(rejected_part)
        except PassportDocumentStagingError as exc:
            rejected.append(RejectedPassportDocument(source.filename, str(exc)))
        except (OSError, ValueError, zipfile.BadZipFile, RuntimeError):
            rejected.append(
                RejectedPassportDocument(
                    source.filename,
                    "Unreadable or encrypted ZIP archive",
                )
            )
        finally:
            source.stream.seek(0)
        return accepted, rejected

    def _collect_direct(
        self,
        source: PassportDocumentUploadSource,
        *,
        workspace: PassportDocumentImportWorkspace,
        allowed_staff_codes: set[str] | None,
    ) -> tuple[list[PassportDocumentFile], list[RejectedPassportDocument]]:
        try:
            content = _read_exact_stream(
                source.stream,
                expected_bytes=source.size_bytes,
                maximum_bytes=MAX_MEMBER_BYTES,
                label="Uploaded passport image",
            )
        except (OSError, PassportDocumentStagingError, ValueError) as exc:
            return [], [RejectedPassportDocument(source.filename, str(exc))]
        return self._validate_one(
            filename=source.filename,
            content=content,
            declared_type=source.declared_content_type,
            workspace=workspace,
            allowed_staff_codes=allowed_staff_codes,
        )

    def _validate_one(
        self,
        *,
        filename: str,
        content: bytes,
        declared_type: str | None,
        workspace: PassportDocumentImportWorkspace,
        allowed_staff_codes: set[str] | None,
    ) -> tuple[list[PassportDocumentFile], list[RejectedPassportDocument]]:
        basename = PurePosixPath(filename.replace("\\", "/")).name
        parsed = self._parse_name(basename)
        if parsed is None:
            return [], [self._invalid_filename(filename)]
        staff_code, document_type = parsed
        if allowed_staff_codes is not None and staff_code not in allowed_staff_codes:
            return [], [
                RejectedPassportDocument(filename, "Staff code was not found in this group")
            ]
        try:
            upload = self._validator.validate(
                content=content,
                filename=basename,
                declared_content_type=declared_type,
            )
            staged = workspace.stage(upload)
        except ImageValidationError as exc:
            return [], [RejectedPassportDocument(filename, exc.message)]
        except PassportDocumentStagingError as exc:
            return [], [RejectedPassportDocument(filename, str(exc))]
        return [
            PassportDocumentFile(
                filename=basename,
                staff_code=staff_code,
                document_type=document_type,
                upload=staged,
            )
        ], []

    @staticmethod
    def _invalid_filename(filename: str) -> RejectedPassportDocument:
        return RejectedPassportDocument(
            filename,
            "Expected filename STF_<staffcode>_PHOTO, _FRONT, or _BACK "
            "with a JPEG, PNG, or WebP extension",
        )

    @staticmethod
    def _parse_name(filename: str) -> tuple[str, str] | None:
        match = re.fullmatch(_NAME_PATTERN, filename, flags=re.IGNORECASE)
        if not match:
            return None
        return match.group("staff_code").upper(), match.group("document_type").lower()


def _read_exact_stream(
    stream: IO[bytes],
    *,
    expected_bytes: int,
    maximum_bytes: int,
    label: str,
) -> bytes:
    stream.seek(0)
    try:
        return _read_forward_stream_exact(
            stream,
            expected_bytes=expected_bytes,
            maximum_bytes=maximum_bytes,
            label=label,
        )
    finally:
        stream.seek(0)


def _read_forward_stream_exact(
    stream: IO[bytes],
    *,
    expected_bytes: int,
    maximum_bytes: int,
    label: str,
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
