"""Prepare attempt-owned object keys and ordered passport upload specifications."""

from __future__ import annotations

import uuid
from typing import Protocol

from app.domain.entities.entities import ClientGroup


class DraftKeyFactory(Protocol):
    def __call__(
        self,
        *,
        agency_id: uuid.UUID,
        group_id: uuid.UUID,
        unique_id: uuid.UUID,
        document_type: str | None,
        content_type: str,
    ) -> str: ...


UploadSpec = tuple[str | None, bytes, str, str]


def prepare_passport_uploads(
    *,
    group: ClientGroup,
    unique_id: uuid.UUID,
    file_content: bytes,
    content_type: str,
    passport_back: tuple[bytes, str, str] | None,
    passport_photo: tuple[bytes, str, str] | None,
    passport_cover: tuple[bytes, str, str] | None,
    passport_back_cover: tuple[bytes, str, str] | None,
    draft_key: DraftKeyFactory,
) -> tuple[str, list[UploadSpec]]:
    front_key = (
        draft_key(
            agency_id=group.agency_id,
            group_id=group.id,
            unique_id=unique_id,
            document_type=None,
            content_type=content_type,
        )
        if file_content
        else ""
    )
    upload_specs: list[tuple[str | None, bytes, str, str]] = (
        [
            (None, file_content, content_type, front_key),
        ]
        if file_content
        else []
    )
    for document_type, upload in (
        ("back", passport_back),
        ("photo", passport_photo),
        ("cover", passport_cover),
        ("back_cover", passport_back_cover),
    ):
        if not upload:
            continue
        upload_content, upload_content_type, _upload_filename = upload
        upload_specs.append(
            (
                document_type,
                upload_content,
                upload_content_type,
                draft_key(
                    agency_id=group.agency_id,
                    group_id=group.id,
                    unique_id=unique_id,
                    document_type=document_type,
                    content_type=upload_content_type,
                ),
            )
        )
    return front_key, upload_specs
