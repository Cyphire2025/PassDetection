"""Coordinate bounded, filename-driven staff passport document imports."""

from __future__ import annotations

import re as re
import stat as stat
import tempfile as tempfile
import zipfile
from dataclasses import dataclass as dataclass
from dataclasses import field as field
from pathlib import PurePosixPath as PurePosixPath
from typing import IO as IO

from app.domain.exceptions.exceptions import ImageValidationError as ImageValidationError
from app.infrastructure.imports.passport_document_images import _NAME_PATTERN as _NAME_PATTERN
from app.infrastructure.imports.passport_document_images import (
    invalid_passport_document_filename,
    parse_passport_document_name,
    validate_passport_document_image,
)
from app.infrastructure.imports.passport_document_streams import (
    MAX_MEMBER_BYTES,
    PassportDocumentStagingError,
    _read_exact_stream,
)
from app.infrastructure.imports.passport_document_streams import (
    PASSPORT_DOCUMENT_READ_CHUNK_BYTES as PASSPORT_DOCUMENT_READ_CHUNK_BYTES,
)
from app.infrastructure.imports.passport_document_streams import (
    _read_forward_stream_exact as _read_forward_stream_exact,
)
from app.infrastructure.imports.passport_document_workspace import (
    MAX_STAGED_CANONICAL_BYTES as MAX_STAGED_CANONICAL_BYTES,
)
from app.infrastructure.imports.passport_document_workspace import (
    PASSPORT_DOCUMENT_SPOOL_MEMORY_BYTES as PASSPORT_DOCUMENT_SPOOL_MEMORY_BYTES,
)
from app.infrastructure.imports.passport_document_workspace import (
    PassportDocumentFile as PassportDocumentFile,
)
from app.infrastructure.imports.passport_document_workspace import (
    PassportDocumentImportWorkspace as PassportDocumentImportWorkspace,
)
from app.infrastructure.imports.passport_document_workspace import (
    PassportDocumentUploadSource as PassportDocumentUploadSource,
)
from app.infrastructure.imports.passport_document_workspace import (
    RejectedPassportDocument as RejectedPassportDocument,
)
from app.infrastructure.imports.passport_document_workspace import (
    StagedValidatedUpload as StagedValidatedUpload,
)
from app.infrastructure.imports.passport_zip_admission import (
    PassportZipMemberLimitError as PassportZipMemberLimitError,
)
from app.infrastructure.imports.passport_zip_admission import (
    admit_passport_zip_directory as admit_passport_zip_directory,
)
from app.infrastructure.imports.passport_zip_members import (
    MAX_COMPRESSION_RATIO as MAX_COMPRESSION_RATIO,
)
from app.infrastructure.imports.passport_zip_members import (
    MAX_UNCOMPRESSED_BYTES as MAX_UNCOMPRESSED_BYTES,
)
from app.infrastructure.imports.passport_zip_members import _ImportBudget
from app.infrastructure.imports.passport_zip_reader import collect_passport_zip
from app.infrastructure.security.upload_validator import UploadValidator
from app.infrastructure.security.upload_validator import ValidatedUpload as ValidatedUpload

MAX_ARCHIVES = 8

MAX_DIRECT_FILES = 500

MAX_ARCHIVE_BYTES = 128 * 1024 * 1024

MAX_TOTAL_SOURCE_BYTES = 256 * 1024 * 1024

MAX_MEMBERS = 5000


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
            return (accepted, rejected)
        if any((source.size_bytes < 0 for source in sources)):
            return (accepted, [RejectedPassportDocument("upload", "Upload size is invalid")])
        total_source_bytes = sum((source.size_bytes for source in sources))
        if total_source_bytes > MAX_TOTAL_SOURCE_BYTES:
            return (
                accepted,
                [
                    RejectedPassportDocument(
                        "upload",
                        "Upload exceeds the 256 MB request staging limit; split it into smaller batches",
                    )
                ],
            )
        archive_count = 0
        direct_count = 0
        budget = _ImportBudget()
        for source in sources:
            if source.size_bytes > MAX_ARCHIVE_BYTES:
                rejected.append(
                    RejectedPassportDocument(
                        source.filename, "File exceeds the 128 MB bounded import limit"
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
                            source.filename, f"Upload at most {MAX_ARCHIVES} ZIP archives at a time"
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
                    source, workspace=workspace, allowed_staff_codes=allowed_staff_codes
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
                        item.filename, "Duplicate document type for this staff code"
                    )
                )
            else:
                seen.add(key)
                unique.append(item)
        return (unique, rejected)

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
        return collect_passport_zip(
            self._validator,
            source,
            workspace=workspace,
            budget=budget,
            allowed_staff_codes=allowed_staff_codes,
            max_members=MAX_MEMBERS,
        )

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
            return ([], [RejectedPassportDocument(source.filename, str(exc))])
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
        return validate_passport_document_image(
            self._validator,
            filename=filename,
            content=content,
            declared_type=declared_type,
            workspace=workspace,
            allowed_staff_codes=allowed_staff_codes,
        )

    @staticmethod
    def _invalid_filename(filename: str) -> RejectedPassportDocument:
        return invalid_passport_document_filename(filename)

    @staticmethod
    def _parse_name(filename: str) -> tuple[str, str] | None:
        return parse_passport_document_name(filename)
