"""Filename policy and canonical image validation shared by direct and ZIP imports."""

from __future__ import annotations

import re
from pathlib import PurePosixPath

from app.domain.exceptions.exceptions import ImageValidationError
from app.infrastructure.imports.passport_document_streams import PassportDocumentStagingError
from app.infrastructure.imports.passport_document_workspace import (
    PassportDocumentFile,
    PassportDocumentImportWorkspace,
    RejectedPassportDocument,
)
from app.infrastructure.security.upload_validator import UploadValidator

_NAME_PATTERN = "^STF_(?P<staff_code>[A-Za-z0-9-]{1,80})_(?P<document_type>PHOTO|FRONT|BACK)\\.(?P<extension>jpe?g|png|webp)$"


def invalid_passport_document_filename(filename: str) -> RejectedPassportDocument:
    return RejectedPassportDocument(
        filename,
        "Expected filename STF_<staffcode>_PHOTO, _FRONT, or _BACK with a JPEG, PNG, or WebP extension",
    )


def parse_passport_document_name(filename: str) -> tuple[str, str] | None:
    match = re.fullmatch(_NAME_PATTERN, filename, flags=re.IGNORECASE)
    if not match:
        return None
    return (match.group("staff_code").upper(), match.group("document_type").lower())


def validate_passport_document_image(
    validator: UploadValidator,
    *,
    filename: str,
    content: bytes,
    declared_type: str | None,
    workspace: PassportDocumentImportWorkspace,
    allowed_staff_codes: set[str] | None,
) -> tuple[list[PassportDocumentFile], list[RejectedPassportDocument]]:
    basename = PurePosixPath(filename.replace("\\", "/")).name
    parsed = parse_passport_document_name(basename)
    if parsed is None:
        return ([], [invalid_passport_document_filename(filename)])
    staff_code, document_type = parsed
    if allowed_staff_codes is not None and staff_code not in allowed_staff_codes:
        return ([], [RejectedPassportDocument(filename, "Staff code was not found in this group")])
    try:
        upload = validator.validate(
            content=content, filename=basename, declared_content_type=declared_type
        )
        staged = workspace.stage(upload)
    except ImageValidationError as exc:
        return ([], [RejectedPassportDocument(filename, exc.message)])
    except PassportDocumentStagingError as exc:
        return ([], [RejectedPassportDocument(filename, str(exc))])
    return (
        [
            PassportDocumentFile(
                filename=basename, staff_code=staff_code, document_type=document_type, upload=staged
            )
        ],
        [],
    )
