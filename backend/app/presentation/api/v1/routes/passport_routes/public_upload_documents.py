"""Validate configured multipart documents and build their submission payload."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import HTTPException, UploadFile, status

from app.domain.entities.entities import ClientGroup
from app.domain.exceptions.exceptions import PassDetectionError
from app.domain.value_objects.upload_configuration import (
    MAX_PUBLIC_DOCUMENT_BYTES,
    PASSPORT_PAGE_LABELS,
    validate_documents,
    validate_visa_photo_source,
)
from app.infrastructure.security.upload_validator import ValidatedUpload


def _upload_tuple(upload: ValidatedUpload | None) -> tuple[bytes, str, str] | None:
    if upload is None:
        return None
    return upload.content, upload.content_type, upload.filename


async def validate_public_upload_documents(
    *,
    group: ClientGroup,
    acquisition_mode: str,
    visa_photo_source: str | None,
    file: UploadFile | None,
    passport_back_file: UploadFile | None,
    passport_photo_file: UploadFile | None,
    passport_cover_file: UploadFile | None,
    passport_back_cover_file: UploadFile | None,
    validator: Callable[..., Awaitable[ValidatedUpload]],
) -> dict[str, Any]:
    pages = {
        "front": file,
        "back": passport_back_file,
        "cover": passport_cover_file,
        "back_cover": passport_back_cover_file,
    }
    try:
        validate_documents(group, pages=pages, mode=acquisition_mode, photo=passport_photo_file)
        validate_visa_photo_source(group, photo=passport_photo_file, source=visa_photo_source)
    except PassDetectionError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=exc.message) from exc

    validated: dict[str, ValidatedUpload] = {}
    for name, upload in {**pages, "photo": passport_photo_file}.items():
        if upload is None:
            continue
        source = visa_photo_source if name == "photo" else acquisition_mode
        validated[name] = await validator(
            upload,
            label=PASSPORT_PAGE_LABELS.get(name, "Visa Photo"),
            max_size_bytes=MAX_PUBLIC_DOCUMENT_BYTES if source == "file" else None,
        )
    front = validated.get("front")
    return {
        "file_content": front.content if front else b"",
        "content_type": front.content_type if front else "image/jpeg",
        "filename": front.filename if front else "",
        "passport_back": _upload_tuple(validated.get("back")),
        "passport_photo": _upload_tuple(validated.get("photo")),
        "passport_cover": _upload_tuple(validated.get("cover")),
        "passport_back_cover": _upload_tuple(validated.get("back_cover")),
        "visa_photo_source": visa_photo_source,
    }
