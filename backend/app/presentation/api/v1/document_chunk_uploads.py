"""Resumable, bounded chunk protocol for bulk travel-document workflows."""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.models import DocumentUploadChunkModel
from app.presentation.api.v1.document_uploads import (
    MAX_DOCUMENT_BATCH_BYTES,
    MAX_DOCUMENT_FILES_PER_REQUEST,
    BoundedDocumentUpload,
)

MAX_LOGICAL_DOCUMENT_FILES = 1_500
MAX_LOGICAL_DOCUMENT_BYTES = 2 * 1024 * 1024 * 1024
MAX_DOCUMENT_FILES_PER_CHUNK = MAX_DOCUMENT_FILES_PER_REQUEST


def document_upload_advisory_lock_key(*, workflow: str, upload_id: uuid.UUID) -> int:
    """Return a stable signed bigint key for PostgreSQL transaction locking."""

    digest = hashlib.sha256(f"document-upload:{workflow}:{upload_id}".encode()).digest()
    return int.from_bytes(digest[:8], "big", signed=True)


def document_upload_scope_advisory_lock_key(
    *,
    agency_id: uuid.UUID,
    group_id: uuid.UUID,
    document_type: str,
) -> int:
    """Return one stable lock key for distribution-session creation scope."""

    if document_type not in {"visa", "flight_ticket", "other"}:
        raise ValueError("Unsupported distribution document type")
    digest = hashlib.sha256(
        (f"document-upload-scope:distribution:{agency_id}:{group_id}:{document_type}").encode()
    ).digest()
    return int.from_bytes(digest[:8], "big", signed=True)


async def acquire_document_upload_advisory_lock(
    session: AsyncSession,
    *,
    workflow: str,
    upload_id: uuid.UUID,
) -> int:
    """Serialize final manifest decisions even while no receipt row exists."""

    if workflow not in {"rename", "distribution"}:
        raise ValueError("Unsupported document upload workflow")
    lock_key = document_upload_advisory_lock_key(
        workflow=workflow,
        upload_id=upload_id,
    )
    await session.execute(select(func.pg_advisory_xact_lock(lock_key)))
    return lock_key


async def acquire_document_upload_scope_advisory_lock(
    session: AsyncSession,
    *,
    agency_id: uuid.UUID,
    group_id: uuid.UUID,
    document_type: str,
) -> int:
    """Serialize create-or-abort decisions for one distribution ledger."""

    lock_key = document_upload_scope_advisory_lock_key(
        agency_id=agency_id,
        group_id=group_id,
        document_type=document_type,
    )
    await session.execute(select(func.pg_advisory_xact_lock(lock_key)))
    return lock_key


@dataclass(frozen=True, slots=True)
class DocumentChunkMetadata:
    upload_id: uuid.UUID
    chunk_id: uuid.UUID
    chunk_index: int
    expected_chunk_count: int
    expected_file_count: int


def resolve_document_chunk_metadata(
    *,
    upload_id: uuid.UUID | None,
    chunk_id: uuid.UUID | None,
    chunk_index: int | None,
    expected_chunk_count: int | None,
    expected_file_count: int | None,
) -> DocumentChunkMetadata | None:
    """Validate optional chunk fields while preserving legacy one-request clients."""

    values = (
        upload_id,
        chunk_id,
        chunk_index,
        expected_chunk_count,
        expected_file_count,
    )
    if all(value is None for value in values):
        return None
    if any(value is None for value in values):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Upload session metadata is incomplete",
        )
    assert upload_id is not None
    assert chunk_id is not None
    assert chunk_index is not None
    assert expected_chunk_count is not None
    assert expected_file_count is not None
    if not 1 <= expected_chunk_count <= MAX_LOGICAL_DOCUMENT_FILES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"An upload may contain at most {MAX_LOGICAL_DOCUMENT_FILES} chunks",
        )
    if not 1 <= expected_file_count <= MAX_LOGICAL_DOCUMENT_FILES:
        raise HTTPException(
            status_code=413,
            detail=f"Upload at most {MAX_LOGICAL_DOCUMENT_FILES} PDFs at a time",
        )
    if not (
        expected_chunk_count
        <= expected_file_count
        <= expected_chunk_count * MAX_DOCUMENT_FILES_PER_CHUNK
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The upload chunk manifest cannot contain the declared file total",
        )
    if not 0 <= chunk_index < expected_chunk_count:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Upload chunk index is outside the declared session",
        )
    return DocumentChunkMetadata(
        upload_id=upload_id,
        chunk_id=chunk_id,
        chunk_index=chunk_index,
        expected_chunk_count=expected_chunk_count,
        expected_file_count=expected_file_count,
    )


def validate_document_chunk_size(
    metadata: DocumentChunkMetadata | None,
    *,
    file_count: int,
) -> None:
    if not 1 <= file_count <= MAX_DOCUMENT_FILES_PER_CHUNK:
        raise HTTPException(
            status_code=413,
            detail=(
                "Each physical upload request may contain at most "
                f"{MAX_DOCUMENT_FILES_PER_CHUNK} PDFs"
            ),
        )


def document_chunk_fingerprint(uploads: list[BoundedDocumentUpload]) -> str:
    """Bind a chunk ID to the ordered filenames and exact bytes it committed."""

    digest = hashlib.sha256()
    for upload in uploads:
        filename = upload.filename.encode("utf-8")
        digest.update(len(filename).to_bytes(4, "big"))
        digest.update(filename)
        digest.update(len(upload.content).to_bytes(8, "big"))
        digest.update(upload.content)
    return digest.hexdigest()


def validate_existing_document_chunk(
    receipt: DocumentUploadChunkModel,
    *,
    metadata: DocumentChunkMetadata,
    agency_id: uuid.UUID,
    workflow: str,
    group_id: uuid.UUID | None,
    document_type: str | None,
    fingerprint: str,
    file_count: int,
    byte_count: int,
) -> None:
    """Fail closed if a chunk token is replayed with different scope or bytes."""

    matches = (
        receipt.upload_id == metadata.upload_id
        and receipt.agency_id == agency_id
        and receipt.workflow == workflow
        and receipt.group_id == group_id
        and receipt.document_type == document_type
        and receipt.chunk_index == metadata.chunk_index
        and receipt.expected_chunk_count == metadata.expected_chunk_count
        and receipt.expected_file_count == metadata.expected_file_count
        and receipt.file_count == file_count
        and receipt.byte_count == byte_count
        and receipt.fingerprint == fingerprint
    )
    if not matches:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This upload chunk token was already used with different data",
        )


def validate_next_document_chunk(
    receipts: list[DocumentUploadChunkModel],
    *,
    metadata: DocumentChunkMetadata,
    incoming_file_count: int,
    incoming_byte_count: int,
) -> bool:
    """Require one immutable manifest and contiguous chunks; return completion."""

    ordered = sorted(receipts, key=lambda item: item.chunk_index)
    if [item.chunk_index for item in ordered] != list(range(len(ordered))):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The upload session has an invalid chunk sequence",
        )
    for receipt in ordered:
        if (
            receipt.upload_id != metadata.upload_id
            or receipt.expected_chunk_count != metadata.expected_chunk_count
            or receipt.expected_file_count != metadata.expected_file_count
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="The upload session manifest does not match its first chunk",
            )
    if metadata.chunk_index != len(ordered):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Upload chunk {len(ordered) + 1} must be completed next",
        )
    completed_files = sum(item.file_count for item in ordered)
    completed_bytes = sum(item.byte_count for item in ordered)
    resulting_files = completed_files + incoming_file_count
    resulting_bytes = completed_bytes + incoming_byte_count
    resulting_chunks = len(ordered) + 1
    if resulting_files > metadata.expected_file_count:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The upload contains more files than its original selection",
        )
    if not 1 <= incoming_byte_count <= MAX_DOCUMENT_BATCH_BYTES:
        raise HTTPException(
            status_code=413,
            detail="The physical PDF upload chunk is too large",
        )
    if resulting_bytes > MAX_LOGICAL_DOCUMENT_BYTES:
        raise HTTPException(
            status_code=413,
            detail="The complete PDF selection exceeds the 2 GB safety limit",
        )
    complete = resulting_chunks == metadata.expected_chunk_count
    if complete != (resulting_files == metadata.expected_file_count):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The upload chunk and file totals do not complete together",
        )
    return complete


def resolve_concurrent_document_chunk_replay(
    receipts: list[DocumentUploadChunkModel],
    *,
    metadata: DocumentChunkMetadata,
    agency_id: uuid.UUID,
    workflow: str,
    group_id: uuid.UUID | None,
    document_type: str | None,
    fingerprint: str,
    file_count: int,
    byte_count: int,
) -> DocumentUploadChunkModel | None:
    """Resolve a receipt that won a same-index race after the initial read.

    Exact bytes and scope are idempotent success even if two browser retries
    reached different workers.  A different payload at the same index remains
    a fail-closed conflict.
    """

    receipt = next(
        (item for item in receipts if item.chunk_index == metadata.chunk_index),
        None,
    )
    if receipt is None:
        return None
    validate_existing_document_chunk(
        receipt,
        metadata=metadata,
        agency_id=agency_id,
        workflow=workflow,
        group_id=group_id,
        document_type=document_type,
        fingerprint=fingerprint,
        file_count=file_count,
        byte_count=byte_count,
    )
    return receipt


def new_document_chunk_receipt(
    *,
    metadata: DocumentChunkMetadata,
    agency_id: uuid.UUID,
    workflow: str,
    group_id: uuid.UUID | None,
    document_type: str | None,
    fingerprint: str,
    file_count: int,
    byte_count: int,
    accepted_count: int,
    rejected_count: int,
    rejected_documents: list[dict[str, str]] | None = None,
) -> DocumentUploadChunkModel:
    rejection_details = rejected_documents or []
    if accepted_count + rejected_count != file_count:
        raise ValueError("Chunk result counts must equal its physical file count")
    if workflow == "distribution" and len(rejection_details) != rejected_count:
        raise ValueError("Every rejected distribution PDF requires durable review details")
    if not 1 <= byte_count <= MAX_DOCUMENT_BATCH_BYTES:
        raise ValueError("Chunk bytes exceed the physical request envelope")
    return DocumentUploadChunkModel(
        id=metadata.chunk_id,
        upload_id=metadata.upload_id,
        agency_id=agency_id,
        workflow=workflow,
        group_id=group_id,
        document_type=document_type,
        chunk_index=metadata.chunk_index,
        expected_chunk_count=metadata.expected_chunk_count,
        expected_file_count=metadata.expected_file_count,
        file_count=file_count,
        byte_count=byte_count,
        fingerprint=fingerprint,
        accepted_count=accepted_count,
        rejected_count=rejected_count,
        rejected_documents=rejection_details,
        created_at=datetime.now(tz=UTC),
    )
