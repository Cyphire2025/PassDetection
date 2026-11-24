"""Immutable import targets and sequential owned native/S3 work before row locks."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from functools import partial

from fastapi import HTTPException

from app.infrastructure.database.models import PassportSubmissionModel
from app.infrastructure.documents.storage_transfers import run_bounded_storage_operations
from app.infrastructure.imports.passport_document_importer import PassportDocumentFile
from app.infrastructure.storage.minio_repository import MinioStorageRepository

DOCUMENT_IMAGE_ATTRIBUTES = {
    "front": "image_s3_key",
    "photo": "passport_photo_s3_key",
    "back": "passport_back_s3_key",
}


@dataclass(frozen=True)
class PassportDocumentImportTarget:
    item: PassportDocumentFile
    submission_id: uuid.UUID
    original_storage_key: str | None
    storage_key: str


def prepare_document_import_targets(
    matched: Sequence[PassportDocumentFile],
    submissions: Mapping[str, PassportSubmissionModel],
    *,
    agency_id: uuid.UUID,
    group_id: uuid.UUID,
) -> tuple[PassportDocumentImportTarget, ...]:
    targets = []
    for item in matched:
        submission = submissions.get(item.staff_code)
        if submission is None:
            raise HTTPException(409, "The passenger changed. Refresh the group and try again.")
        suffix = item.upload.filename.rsplit(".", 1)[-1]
        key = (
            f"passport-bulk/{agency_id}/{group_id}/{submission.id}/"
            f"{uuid.uuid4().hex}-{item.document_type}.{suffix}"
        )
        targets.append(
            PassportDocumentImportTarget(
                item=item,
                submission_id=submission.id,
                original_storage_key=getattr(
                    submission, DOCUMENT_IMAGE_ATTRIBUTES[item.document_type]
                ),
                storage_key=key,
            )
        )
    return tuple(targets)


async def stage_document_import_targets(
    storage: MinioStorageRepository,
    targets: Sequence[PassportDocumentImportTarget],
    uploaded_keys: list[str],
) -> None:
    for target in targets:
        upload = target.item.upload
        content = (
            await run_bounded_storage_operations(
                [partial(asyncio.to_thread, upload.read_content)],
                concurrency=1,
            )
        )[0]
        uploaded_keys.append(target.storage_key)
        await run_bounded_storage_operations(
            [partial(storage.upload_file, content, target.storage_key, upload.content_type)],
            concurrency=1,
        )
