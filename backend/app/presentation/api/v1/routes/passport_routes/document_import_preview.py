"""Bounded native passport validation and staff-code preview projection."""

from __future__ import annotations

import asyncio
import uuid
from functools import partial

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.models import PassportSubmissionModel
from app.infrastructure.documents.storage_transfers import run_bounded_storage_operations
from app.infrastructure.imports.passport_document_importer import (
    PassportDocumentFile,
    PassportDocumentImporter,
    PassportDocumentImportWorkspace,
    PassportDocumentUploadSource,
    RejectedPassportDocument,
)
from app.presentation.api.v1.schemas.passport_schemas import (
    PassportDocumentImportItem,
    PassportDocumentImportPreviewResponse,
)

from .constants import _staff_code_for_submission


async def _passport_document_preview(
    *,
    group_id: uuid.UUID,
    files: list[UploadFile],
    session: AsyncSession,
    workspace: PassportDocumentImportWorkspace,
) -> tuple[PassportDocumentImportPreviewResponse, list[PassportDocumentFile]]:
    result = await session.execute(
        select(PassportSubmissionModel).where(PassportSubmissionModel.group_id == group_id)
    )
    submissions = list(result.scalars().all())
    by_staff_code = {
        code: submission
        for submission in submissions
        if (code := _staff_code_for_submission(submission))
    }
    # Request-owned framework and canonical spools must outlive their native readers.
    sources = (
        await run_bounded_storage_operations(
            [partial(asyncio.to_thread, _passport_document_upload_sources, files)],
            concurrency=1,
        )
    )[0]
    accepted, rejected = (
        await run_bounded_storage_operations(
            [
                partial(
                    asyncio.to_thread,
                    PassportDocumentImporter().collect,
                    sources,
                    workspace=workspace,
                    allowed_staff_codes=set(by_staff_code),
                )
            ],
            concurrency=1,
        )
    )[0]
    response_accepted: list[PassportDocumentImportItem] = []
    matched: list[PassportDocumentFile] = []
    seen: set[tuple[uuid.UUID, str]] = set()
    for item in accepted:
        submission = by_staff_code.get(item.staff_code)
        if not submission:
            rejected.append(
                RejectedPassportDocument(item.filename, "Staff code was not found in this group")
            )
            continue
        key = (submission.id, item.document_type)
        if key in seen:
            rejected.append(
                RejectedPassportDocument(
                    item.filename, "Duplicate document type for this passenger"
                )
            )
            continue
        seen.add(key)
        matched.append(item)
        response_accepted.append(
            PassportDocumentImportItem(
                filename=item.filename,
                staff_code=item.staff_code,
                document_type=item.document_type,
                passenger_id=submission.id,
                passenger_name=submission.client_name,
                accepted=True,
            )
        )
    response_rejected = [
        PassportDocumentImportItem(filename=item.filename, accepted=False, reason=item.reason)
        for item in rejected
    ]
    return PassportDocumentImportPreviewResponse(
        group_id=group_id,
        total_count=len(response_accepted) + len(response_rejected),
        accepted_count=len(response_accepted),
        rejected_count=len(response_rejected),
        accepted_documents=response_accepted,
        rejected_documents=response_rejected,
    ), matched


def _passport_document_upload_sources(
    files: list[UploadFile],
) -> list[PassportDocumentUploadSource]:
    """Measure seekable framework spools without materializing their bodies."""

    sources: list[PassportDocumentUploadSource] = []
    for upload in files:
        stream = upload.file
        try:
            stream.seek(0, 2)
            size_bytes = stream.tell()
            stream.seek(0)
        except (OSError, ValueError):
            size_bytes = -1
        sources.append(
            PassportDocumentUploadSource(
                filename=upload.filename or "upload",
                stream=stream,
                size_bytes=size_bytes,
                declared_content_type=upload.content_type,
            )
        )
    return sources


# Preserve established private helper import/pickle identities.
_passport_document_preview.__module__ = (
    "app.presentation.api.v1.routes.passport_routes.document_import"
)
_passport_document_upload_sources.__module__ = (
    "app.presentation.api.v1.routes.passport_routes.document_import"
)
