"""Admit ZIP paths, entry metadata and cumulative extraction budgets."""

from __future__ import annotations

import stat
import zipfile
from dataclasses import dataclass
from pathlib import PurePosixPath

from app.infrastructure.imports.passport_document_images import (
    invalid_passport_document_filename,
    parse_passport_document_name,
)
from app.infrastructure.imports.passport_document_streams import (
    MAX_MEMBER_BYTES,
    PassportDocumentStagingError,
)
from app.infrastructure.imports.passport_document_workspace import RejectedPassportDocument

MAX_UNCOMPRESSED_BYTES = 512 * 1024 * 1024

MAX_COMPRESSION_RATIO = 100


@dataclass(slots=True)
class _ImportBudget:
    uncompressed_bytes: int = 0


def admit_passport_zip_member(
    info: zipfile.ZipInfo,
    *,
    source_filename: str,
    budget: _ImportBudget,
    allowed_staff_codes: set[str] | None,
) -> str | RejectedPassportDocument | None:
    """Return a usable basename, a rejection, or None for a directory.

    Cumulative extraction quota failure ends this archive through the reader's
    existing staging-error boundary; other rejected entries do not stop it.
    """
    path = PurePosixPath(info.filename.replace("\\", "/"))
    if not info.filename or path.is_absolute() or ".." in path.parts:
        return RejectedPassportDocument(info.filename or source_filename, "Unsafe ZIP path")
    if info.is_dir():
        return None
    if stat.S_ISLNK(info.external_attr >> 16):
        return RejectedPassportDocument(info.filename, "ZIP symlink entries are not allowed")
    if info.file_size > MAX_MEMBER_BYTES:
        return RejectedPassportDocument(info.filename, "Image exceeds the 20 MB per-file limit")
    budget.uncompressed_bytes += info.file_size
    if budget.uncompressed_bytes > MAX_UNCOMPRESSED_BYTES:
        raise PassportDocumentStagingError(
            "ZIP imports exceed the 512 MB extracted-size staging limit"
        )
    if info.file_size > 0 and info.compress_size <= 0:
        return RejectedPassportDocument(info.filename, "Suspicious ZIP compression metadata")
    if info.compress_size > 0 and info.file_size / info.compress_size > MAX_COMPRESSION_RATIO:
        return RejectedPassportDocument(info.filename, "Suspicious ZIP compression ratio")
    basename = path.name
    parsed = parse_passport_document_name(basename)
    if parsed is None:
        return invalid_passport_document_filename(info.filename)
    if allowed_staff_codes is not None and parsed[0] not in allowed_staff_codes:
        return RejectedPassportDocument(info.filename, "Staff code was not found in this group")
    return basename
