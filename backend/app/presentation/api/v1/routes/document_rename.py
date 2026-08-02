"""Document rename routes."""

from __future__ import annotations

import asyncio
import re
import threading
import uuid
import zipfile
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from tempfile import SpooledTemporaryFile
from typing import Annotated, BinaryIO, cast
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import Response, StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.core.logging.logger import get_logger
from app.domain.entities.entities import User, UserRole
from app.infrastructure.database.models import (
    AgencyModel,
    DocumentRenameBatchModel,
    DocumentRenameItemModel,
    DocumentUploadChunkModel,
    UserModel,
)
from app.infrastructure.database.session import get_db_session
from app.infrastructure.documents.document_matcher import (
    SUPPORTED_TRAVEL_DOCUMENT_TYPES,
    DocumentMatcher,
    DocumentParserUnavailableError,
    UnsupportedDocumentBatchFormatError,
    classify_documents_bounded,
)
from app.infrastructure.documents.pdf_parser_sandbox import (
    bounded_pdf_batch_timeout_seconds,
)
from app.infrastructure.documents.storage_cleanup import (
    persist_storage_cleanup_job,
    process_storage_cleanup_job,
    stage_storage_cleanup_jobs,
)
from app.infrastructure.documents.storage_transfers import (
    finish_cleanup_despite_cancellation,
    run_bounded_storage_operations,
)
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.infrastructure.storage.minio_repository import MinioStorageRepository
from app.presentation.api.v1.document_chunk_uploads import (
    acquire_document_upload_advisory_lock,
    document_chunk_fingerprint,
    new_document_chunk_receipt,
    resolve_concurrent_document_chunk_replay,
    resolve_document_chunk_metadata,
    validate_document_chunk_size,
    validate_existing_document_chunk,
    validate_next_document_chunk,
)
from app.presentation.api.v1.document_uploads import read_bounded_document_uploads
from app.presentation.api.v1.schemas.document_rename_schemas import (
    DeleteRenameBatchesRequest,
    DeleteRenameBatchesResponse,
    RenameDocumentBatchResponse,
    RenameDocumentBatchSummaryResponse,
    RenameDocumentItemResponse,
)
from app.presentation.dependencies.auth import get_current_active_user
from app.presentation.dependencies.csrf import require_cookie_csrf

router = APIRouter()
logger = get_logger(__name__)
MAX_RENAME_ARCHIVE_UNCOMPRESSED_BYTES = 512 * 1024 * 1024
RENAME_ARCHIVE_FETCH_BATCH_SIZE = 8
_RENAME_ARCHIVE_ADMISSION = threading.BoundedSemaphore(value=1)


def _ensure_allowed(current_user: User) -> uuid.UUID:
    if not current_user.agency_id or current_user.role == UserRole.AGENCY_COORDINATOR:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions"
        )
    return current_user.agency_id


async def _lock_active_rename_actor(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    agency_id: uuid.UUID,
    expected_role: UserRole,
) -> UserModel:
    """Re-authorize the unchanged actor role and agency under row locks."""

    result = await session.execute(
        select(UserModel)
        .join(AgencyModel, AgencyModel.id == UserModel.agency_id)
        .where(
            UserModel.id == user_id,
            UserModel.agency_id == agency_id,
            UserModel.is_active.is_(True),
            UserModel.deleted_at.is_(None),
            UserModel.role == expected_role.value,
            AgencyModel.is_active.is_(True),
        )
        .with_for_update(of=(UserModel, AgencyModel))  # type: ignore[arg-type]
        .execution_options(populate_existing=True)
    )
    actor = result.scalar_one_or_none()
    if actor is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your account or agency is no longer authorized for document rename.",
        )
    return actor


def _role_value(role: UserRole | str) -> str:
    return role.value if isinstance(role, UserRole) else role


def _batch_filters_for_identity(
    *,
    user_id: uuid.UUID,
    role: UserRole | str,
    agency_id: uuid.UUID,
) -> list[ColumnElement[bool]]:
    filters = [DocumentRenameBatchModel.agency_id == agency_id]
    if _role_value(role) == UserRole.AGENCY_STAFF.value:
        filters.append(DocumentRenameBatchModel.created_by_user_id == user_id)
    return filters


def _batch_filters(
    current_user: User,
    agency_id: uuid.UUID,
) -> list[ColumnElement[bool]]:
    return _batch_filters_for_identity(
        user_id=current_user.id,
        role=current_user.role,
        agency_id=agency_id,
    )


def _document_label(detected_type: str) -> str:
    if detected_type == "visa":
        return "VISA"
    if detected_type == "flight_ticket":
        return "TICKET"
    return "DOCUMENT"


def _display_type(detected_type: str) -> str:
    if detected_type == "flight_ticket":
        return "flight ticket"
    return detected_type


def _safe_part(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9]+", "_", value.strip()).strip("_")
    return cleaned[:120] or "UNKNOWN"


def _renamed_filename(name: str | None, detected_type: str, used: set[str]) -> str:
    base_name = _safe_part(name or "UNKNOWN_PASSENGER").upper()
    base = f"{base_name}_{_document_label(detected_type)}"
    filename = f"{base}.pdf"
    counter = 2
    while filename in used:
        filename = f"{base}_{counter}.pdf"
        counter += 1
    used.add(filename)
    return filename


def _reason(name: str | None, detected_type: str) -> str | None:
    if not name and detected_type == "unknown":
        return "Could not extract passenger name or document type"
    if not name:
        return "Could not extract passenger name"
    if detected_type == "unknown":
        return "Could not detect whether this is a visa or flight ticket"
    return None


async def _stream_archive(
    archive: BinaryIO,
    *,
    release_admission: bool = False,
) -> AsyncIterator[bytes]:
    try:
        while chunk := await asyncio.to_thread(archive.read, 64 * 1024):
            yield chunk
    finally:
        archive.close()
        if release_admission:
            _RENAME_ARCHIVE_ADMISSION.release()


async def _fetch_rename_archive_batch(
    storage: MinioStorageRepository,
    items: list[tuple[uuid.UUID, str, str, str, str]],
) -> list[bytes]:
    """Fetch one bounded window and drain every sibling on failure/cancellation."""

    tasks = [asyncio.create_task(storage.get_file(item[3])) for item in items]
    try:
        return list(await asyncio.gather(*tasks))
    except BaseException:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise


async def _cleanup_owned_rename_storage(
    storage: MinioStorageRepository,
    storage_keys: list[str],
    *,
    agency_id: uuid.UUID,
    batch_id: uuid.UUID,
) -> None:
    if not storage_keys:
        return
    try:
        await storage.delete_files(storage_keys)
    except Exception:
        logger.warning(
            "document_rename_storage_cleanup_deferred",
            object_count=len(storage_keys),
        )
        try:
            await persist_storage_cleanup_job(
                agency_id=agency_id,
                source="document_rename_compensation",
                context_id=str(batch_id),
                storage_keys=storage_keys,
            )
        except Exception as exc:
            logger.error(
                "document_rename_cleanup_tracking_failed",
                batch_id=str(batch_id),
                object_count=len(storage_keys),
                error_type=type(exc).__name__,
            )


def _item_response(item: DocumentRenameItemModel) -> RenameDocumentItemResponse:
    downloadable = (
        item.detected_type in SUPPORTED_TRAVEL_DOCUMENT_TYPES
        and item.status != "rejected"
        and bool(item.storage_key)
    )
    return RenameDocumentItemResponse(
        id=item.id,
        original_filename=item.original_filename,
        renamed_filename=item.renamed_filename,
        detected_type=item.detected_type,
        extracted_name=item.extracted_name,
        extracted_passport_number=item.extracted_passport_number,
        extracted_reference=item.extracted_reference,
        status=item.status,
        reason=item.reason,
        download_url=(f"/api/v1/document-rename/items/{item.id}/download" if downloadable else ""),
    )


def _batch_summary_response(batch: DocumentRenameBatchModel) -> RenameDocumentBatchSummaryResponse:
    return RenameDocumentBatchSummaryResponse(
        batch_id=batch.id,
        title=batch.title,
        status=batch.status,
        total_count=batch.total_count,
        visa_count=batch.visa_count,
        ticket_count=batch.ticket_count,
        unknown_count=batch.unknown_count,
        zip_download_url=f"/api/v1/document-rename/batches/{batch.id}/download.zip",
        created_at=batch.created_at,
    )


async def _batch_response(
    batch: DocumentRenameBatchModel,
    items: list[DocumentRenameItemModel],
) -> RenameDocumentBatchResponse:
    return RenameDocumentBatchResponse(
        batch_id=batch.id,
        title=batch.title,
        status=batch.status,
        total_count=batch.total_count,
        visa_count=batch.visa_count,
        ticket_count=batch.ticket_count,
        unknown_count=batch.unknown_count,
        zip_download_url=f"/api/v1/document-rename/batches/{batch.id}/download.zip",
        created_at=batch.created_at,
        items=[_item_response(item) for item in items],
    )


@router.get("/batches", response_model=list[RenameDocumentBatchSummaryResponse])
async def list_rename_batches(
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> list[RenameDocumentBatchSummaryResponse]:
    agency_id = _ensure_allowed(current_user)
    result = await session.execute(
        select(DocumentRenameBatchModel)
        .where(*_batch_filters(current_user, agency_id))
        .order_by(DocumentRenameBatchModel.created_at.desc())
        .limit(100)
    )
    return [_batch_summary_response(batch) for batch in result.scalars().all()]


@router.post(
    "/batches/bulk-delete",
    response_model=DeleteRenameBatchesResponse,
    dependencies=[Depends(require_cookie_csrf)],
)
async def delete_rename_batches(
    payload: DeleteRenameBatchesRequest,
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> DeleteRenameBatchesResponse:
    agency_id = _ensure_allowed(current_user)
    batch_ids = list(dict.fromkeys(payload.batch_ids))
    batch_result = await session.execute(
        select(DocumentRenameBatchModel)
        .where(
            DocumentRenameBatchModel.id.in_(batch_ids),
            *_batch_filters(current_user, agency_id),
        )
        .order_by(DocumentRenameBatchModel.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    batches = list(batch_result.scalars().all())
    if not batches:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="No rename batches were found"
        )

    found_batch_ids = [batch.id for batch in batches]
    items_result = await session.execute(
        select(DocumentRenameItemModel)
        .where(
            DocumentRenameItemModel.batch_id.in_(found_batch_ids),
            DocumentRenameItemModel.agency_id == agency_id,
        )
        .order_by(DocumentRenameItemModel.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    items = list(items_result.scalars().all())
    receipts_result = await session.execute(
        select(DocumentUploadChunkModel)
        .where(
            DocumentUploadChunkModel.upload_id.in_(found_batch_ids),
            DocumentUploadChunkModel.agency_id == agency_id,
            DocumentUploadChunkModel.workflow == "rename",
        )
        .order_by(DocumentUploadChunkModel.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    receipts = list(receipts_result.scalars().all())
    storage_keys = list({item.storage_key for item in items if item.storage_key})
    cleanup_jobs = stage_storage_cleanup_jobs(
        session,
        agency_id=agency_id,
        source="document_rename_batch_delete",
        context_id=",".join(str(batch_id) for batch_id in sorted(found_batch_ids, key=str)),
        storage_keys=storage_keys,
    )

    for receipt in receipts:
        await session.delete(receipt)
    for batch in batches:
        await session.delete(batch)

    await AuditLogRepository(session).record(
        action="document_rename_deleted",
        entity_type="document_rename_batch",
        entity_id="bulk",
        agency_id=agency_id,
        user_id=current_user.id,
        actor_email=current_user.email,
        metadata={
            "requested_count": len(batch_ids),
            "deleted_count": len(batches),
            "deleted_item_count": len(items),
            "deleted_upload_receipt_count": len(receipts),
            "storage_cleanup_object_count": len(storage_keys),
        },
    )
    await session.commit()
    cleanup_results = []
    for cleanup_job in cleanup_jobs:
        try:
            cleanup_result = await process_storage_cleanup_job(cleanup_job.id)
            if cleanup_result is not None:
                cleanup_results.append(cleanup_result)
        except Exception as exc:
            # The deletion and its durable cleanup job are already committed.  Keep
            # the successful API result truthful and let the periodic worker retry.
            logger.warning(
                "document_rename_cleanup_runner_deferred",
                cleanup_job_id=str(cleanup_job.id),
                object_count=cleanup_job.object_count,
                error_type=type(exc).__name__,
            )
    deleted_storage_objects = sum(
        result.deleted_count for result in cleanup_results if result.completed
    )
    return DeleteRenameBatchesResponse(
        deleted_count=len(batches),
        deleted_storage_objects=deleted_storage_objects,
    )


@router.get("/batches/{batch_id}", response_model=RenameDocumentBatchResponse)
async def get_rename_batch(
    batch_id: uuid.UUID,
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> RenameDocumentBatchResponse:
    agency_id = _ensure_allowed(current_user)
    batch_result = await session.execute(
        select(DocumentRenameBatchModel).where(
            DocumentRenameBatchModel.id == batch_id,
            *_batch_filters(current_user, agency_id),
        )
    )
    batch = batch_result.scalar_one_or_none()
    if not batch:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Rename batch was not found"
        )
    items_result = await session.execute(
        select(DocumentRenameItemModel)
        .where(
            DocumentRenameItemModel.batch_id == batch.id,
            DocumentRenameItemModel.agency_id == agency_id,
        )
        .order_by(DocumentRenameItemModel.renamed_filename.asc())
    )
    return await _batch_response(batch, list(items_result.scalars().all()))


@router.post(
    "/batches",
    response_model=RenameDocumentBatchResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_cookie_csrf)],
)
async def analyze_and_rename_documents(
    files: list[UploadFile] = File(...),
    title: str = Form(...),
    upload_id: Annotated[uuid.UUID | None, Form()] = None,
    chunk_id: Annotated[uuid.UUID | None, Form()] = None,
    chunk_index: Annotated[int | None, Form()] = None,
    expected_chunk_count: Annotated[int | None, Form()] = None,
    expected_file_count: Annotated[int | None, Form()] = None,
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> RenameDocumentBatchResponse:
    agency_id = _ensure_allowed(current_user)
    actor_id = current_user.id
    expected_actor_role = current_user.role
    title = " ".join(title.split())[:160]
    if not title:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Enter a title for this rename batch"
        )
    chunk_metadata = resolve_document_chunk_metadata(
        upload_id=upload_id,
        chunk_id=chunk_id,
        chunk_index=chunk_index,
        expected_chunk_count=expected_chunk_count,
        expected_file_count=expected_file_count,
    )
    validate_document_chunk_size(chunk_metadata, file_count=len(files))

    # Authentication uses this request session and may have opened a read
    # transaction. Release it before bounded upload reads, PDF parsing, and
    # object storage; authorization is repeated under lock before DB staging.
    await session.rollback()
    uploads = await read_bounded_document_uploads(files)
    chunk_byte_count = sum(len(upload.content) for upload in uploads)
    fingerprint = document_chunk_fingerprint(uploads) if chunk_metadata else None

    batch_id = chunk_metadata.upload_id if chunk_metadata else uuid.uuid4()
    existing_batch: DocumentRenameBatchModel | None = None
    if chunk_metadata is not None:
        batch_result = await session.execute(
            select(DocumentRenameBatchModel).where(
                DocumentRenameBatchModel.id == batch_id,
                *_batch_filters(current_user, agency_id),
            )
        )
        existing_batch = batch_result.scalar_one_or_none()
    if chunk_metadata is not None and existing_batch is None:
        collision_result = await session.execute(
            select(DocumentRenameBatchModel.id).where(
                DocumentRenameBatchModel.id == batch_id
            )
        )
        if collision_result.scalar_one_or_none() is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="The upload session is not available to this account",
            )
    if chunk_metadata is not None and existing_batch is not None and existing_batch.title != title:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The upload session title does not match its first chunk",
        )

    existing_receipts: list[DocumentUploadChunkModel] = []
    if chunk_metadata is not None:
        receipt_result = await session.execute(
            select(DocumentUploadChunkModel).where(
                DocumentUploadChunkModel.id == chunk_metadata.chunk_id
            )
        )
        existing_receipt = receipt_result.scalar_one_or_none()
        if existing_receipt is not None:
            assert fingerprint is not None
            validate_existing_document_chunk(
                existing_receipt,
                metadata=chunk_metadata,
                agency_id=agency_id,
                workflow="rename",
                group_id=None,
                document_type=None,
                fingerprint=fingerprint,
                file_count=len(uploads),
                byte_count=chunk_byte_count,
            )
            if existing_batch is None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="The upload session is not available to this account",
                )
            if existing_batch.status != "completed":
                return await _batch_response(existing_batch, [])
            items_result = await session.execute(
                select(DocumentRenameItemModel)
                .where(
                    DocumentRenameItemModel.batch_id == existing_batch.id,
                    DocumentRenameItemModel.agency_id == agency_id,
                )
                .order_by(DocumentRenameItemModel.renamed_filename.asc())
            )
            return await _batch_response(
                existing_batch,
                list(items_result.scalars().all()),
            )
        receipts_result = await session.execute(
            select(DocumentUploadChunkModel)
            .where(
                DocumentUploadChunkModel.upload_id == chunk_metadata.upload_id,
                DocumentUploadChunkModel.agency_id == agency_id,
                DocumentUploadChunkModel.workflow == "rename",
            )
            .order_by(DocumentUploadChunkModel.chunk_index.asc())
        )
        existing_receipts = list(receipts_result.scalars().all())
        if (existing_batch is None) != (len(existing_receipts) == 0):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="The upload session is incomplete and requires administrator review",
            )
        if existing_batch is not None and existing_batch.status == "completed":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This upload session is already complete",
            )
        validate_next_document_chunk(
            existing_receipts,
            metadata=chunk_metadata,
            incoming_file_count=len(uploads),
            incoming_byte_count=chunk_byte_count,
        )

    used_names: set[str] = set()
    if existing_batch is not None:
        items_result = await session.execute(
            select(DocumentRenameItemModel).where(
                DocumentRenameItemModel.batch_id == existing_batch.id,
                DocumentRenameItemModel.agency_id == agency_id,
            )
        )
        used_names = {
            item.renamed_filename for item in items_result.scalars().all()
        }
    if chunk_metadata is not None:
        await session.rollback()

    matcher = DocumentMatcher()
    storage = MinioStorageRepository()
    now = datetime.now(tz=UTC)
    batch = existing_batch or DocumentRenameBatchModel(
        id=batch_id,
        agency_id=agency_id,
        title=title,
        status="processing" if chunk_metadata else "completed",
        total_count=0,
        visa_count=0,
        ticket_count=0,
        unknown_count=0,
        created_by_user_id=actor_id,
        created_at=now,
        updated_at=now,
    )
    items: list[DocumentRenameItemModel] = []
    uploaded_keys: list[str] = []
    try:
        parser_timeout = (
            bounded_pdf_batch_timeout_seconds(len(uploads))
            if chunk_metadata is not None
            else None
        )
        classifications = await asyncio.to_thread(
            classify_documents_bounded,
            matcher,
            [(upload.filename, upload.content, "other") for upload in uploads],
            isolate_pdf_parsing=True,
            batch_timeout_seconds=parser_timeout,
            reject_common_unsupported_format=True,
        )
    except UnsupportedDocumentBatchFormatError as exc:
        raise HTTPException(
            status_code=422,
            detail=str(exc),
        ) from exc
    except DocumentParserUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
            headers={"Retry-After": "1"},
        ) from exc
    storage_operations = []
    try:
        for upload, classification in zip(uploads, classifications, strict=True):
            supported = classification.detected_type in SUPPORTED_TRAVEL_DOCUMENT_TYPES
            detected_type = classification.detected_type if supported else "unknown"
            document_id = uuid.uuid4()
            if supported:
                renamed_filename = _renamed_filename(
                    classification.extracted_name,
                    detected_type,
                    used_names,
                )
                storage_key = (
                    f"document-rename/{batch_id}/{document_id}-{_safe_part(upload.filename)}"
                )
                uploaded_keys.append(storage_key)
                storage_operations.append(
                    lambda payload=upload.content, key=storage_key: storage.upload_file(
                        payload,
                        key,
                        "application/pdf",
                    )
                )
                reason = _reason(classification.extracted_name, detected_type)
                item_status = "renamed" if reason is None else "needs_review"
            else:
                # Rejected bytes are deliberately not persisted. The metadata
                # row keeps the existing batch/review flow while downloads and
                # ZIP creation remain fail-closed.
                renamed_filename = upload.filename
                storage_key = ""
                reason = "Rejected: PDF could not be verified as a visa or flight ticket"
                item_status = "rejected"
            item = DocumentRenameItemModel(
                id=document_id,
                batch_id=batch_id,
                agency_id=agency_id,
                original_filename=upload.filename,
                renamed_filename=renamed_filename,
                storage_key=storage_key,
                content_type="application/pdf",
                detected_type=detected_type,
                extracted_name=classification.extracted_name if supported else None,
                extracted_passport_number=(
                    classification.extracted_passport_number if supported else None
                ),
                extracted_reference=classification.extracted_reference if supported else None,
                status=item_status,
                reason=reason,
                created_at=now,
                updated_at=now,
            )
            items.append(item)
        await run_bounded_storage_operations(storage_operations)
    except BaseException:
        await finish_cleanup_despite_cancellation(
            _cleanup_owned_rename_storage(
                storage,
                uploaded_keys,
                agency_id=agency_id,
                batch_id=batch_id,
            )
        )
        raise

    try:
        actor = await _lock_active_rename_actor(
            session,
            user_id=actor_id,
            agency_id=agency_id,
            expected_role=expected_actor_role,
        )
        complete = True
        if chunk_metadata is not None:
            await acquire_document_upload_advisory_lock(
                session,
                workflow="rename",
                upload_id=chunk_metadata.upload_id,
            )
            serialized_batch_result = await session.execute(
                select(DocumentRenameBatchModel)
                .where(DocumentRenameBatchModel.id == batch_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            serialized_batch = serialized_batch_result.scalar_one_or_none()
            if serialized_batch is not None:
                owner_mismatch = (
                    _role_value(actor.role) == UserRole.AGENCY_STAFF.value
                    and serialized_batch.created_by_user_id != actor.id
                )
                if serialized_batch.agency_id != agency_id or owner_mismatch:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail="The upload session is not available to this account",
                    )
                if serialized_batch.title != title:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail="The upload session title does not match its first chunk",
                    )
                batch = serialized_batch
            locked_receipts_result = await session.execute(
                select(DocumentUploadChunkModel)
                .where(
                    DocumentUploadChunkModel.upload_id == chunk_metadata.upload_id,
                    DocumentUploadChunkModel.workflow == "rename",
                )
                .order_by(DocumentUploadChunkModel.chunk_index.asc())
                .with_for_update()
            )
            locked_receipts = list(locked_receipts_result.scalars().all())
            assert fingerprint is not None
            concurrent_replay = resolve_concurrent_document_chunk_replay(
                locked_receipts,
                metadata=chunk_metadata,
                agency_id=agency_id,
                workflow="rename",
                group_id=None,
                document_type=None,
                fingerprint=fingerprint,
                file_count=len(uploads),
                byte_count=chunk_byte_count,
            )
            if concurrent_replay is not None:
                if serialized_batch is None:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail="The committed upload session is no longer available",
                    )
                replay_items: list[DocumentRenameItemModel] = []
                if serialized_batch.status == "completed":
                    replay_items_result = await session.execute(
                        select(DocumentRenameItemModel)
                        .where(
                            DocumentRenameItemModel.batch_id == batch_id,
                            DocumentRenameItemModel.agency_id == agency_id,
                        )
                        .order_by(DocumentRenameItemModel.renamed_filename.asc())
                    )
                    replay_items = list(replay_items_result.scalars().all())
                replay_response = await _batch_response(serialized_batch, replay_items)
                await session.rollback()
                await _cleanup_owned_rename_storage(
                    storage,
                    uploaded_keys,
                    agency_id=agency_id,
                    batch_id=batch_id,
                )
                return replay_response
            if serialized_batch is not None and existing_batch is None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="The upload session is incomplete and requires administrator review",
                )
            if serialized_batch is None and existing_batch is not None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="The upload session is no longer available",
                )
            complete = validate_next_document_chunk(
                locked_receipts,
                metadata=chunk_metadata,
                incoming_file_count=len(uploads),
                incoming_byte_count=chunk_byte_count,
            )
            session.add(
                new_document_chunk_receipt(
                    metadata=chunk_metadata,
                    agency_id=agency_id,
                    workflow="rename",
                    group_id=None,
                    document_type=None,
                    fingerprint=fingerprint,
                    file_count=len(uploads),
                    byte_count=chunk_byte_count,
                    accepted_count=sum(
                        1 for item in items if item.detected_type != "unknown"
                    ),
                    rejected_count=sum(
                        1 for item in items if item.detected_type == "unknown"
                    ),
                )
            )
        batch.total_count += len(items)
        batch.visa_count += sum(1 for item in items if item.detected_type == "visa")
        batch.ticket_count += sum(
            1 for item in items if item.detected_type == "flight_ticket"
        )
        batch.unknown_count += sum(1 for item in items if item.detected_type == "unknown")
        batch.status = "completed" if complete else "processing"
        batch.updated_at = now
        session.add(batch)
        for item in items:
            session.add(item)
        await AuditLogRepository(session).record(
            action=("document_rename_completed" if complete else "document_rename_chunk_uploaded"),
            entity_type="document_rename_batch",
            entity_id=str(batch.id),
            agency_id=agency_id,
            user_id=actor.id,
            actor_email=actor.email,
            metadata={
                "total_count": batch.total_count,
                "visa_count": batch.visa_count,
                "ticket_count": batch.ticket_count,
                "unknown_count": batch.unknown_count,
                "stored_count": len(uploaded_keys),
                "chunk_index": chunk_metadata.chunk_index if chunk_metadata else None,
            },
        )
        await session.flush()
    except BaseException:
        await session.rollback()
        await finish_cleanup_despite_cancellation(
            _cleanup_owned_rename_storage(
                storage,
                uploaded_keys,
                agency_id=agency_id,
                batch_id=batch_id,
            )
        )
        raise
    try:
        await session.commit()
    except Exception:
        # A COMMIT exception does not prove that PostgreSQL rolled back. Keep
        # uploaded objects that durable rows may reference for safe operational
        # reconciliation; remove only objects proven to be orphaned.
        await session.rollback()
        logger.warning(
            "document_rename_commit_outcome_ambiguous",
            batch_id=str(batch_id),
            object_count=len(uploaded_keys),
        )
        raise
    if chunk_metadata is None:
        return await _batch_response(batch, items)
    if getattr(batch, "status", "completed") != "completed":
        return await _batch_response(batch, [])
    all_items_result = await session.execute(
        select(DocumentRenameItemModel)
        .where(
            DocumentRenameItemModel.batch_id == batch_id,
            DocumentRenameItemModel.agency_id == agency_id,
        )
        .order_by(DocumentRenameItemModel.renamed_filename.asc())
    )
    return await _batch_response(batch, list(all_items_result.scalars().all()))


@router.get("/items/{item_id}/download")
async def download_renamed_document(
    item_id: uuid.UUID,
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> Response:
    agency_id = _ensure_allowed(current_user)
    result = await session.execute(
        select(DocumentRenameItemModel)
        .join(
            DocumentRenameBatchModel,
            DocumentRenameBatchModel.id == DocumentRenameItemModel.batch_id,
        )
        .where(
            DocumentRenameItemModel.id == item_id,
            DocumentRenameItemModel.agency_id == agency_id,
            DocumentRenameItemModel.detected_type.in_(SUPPORTED_TRAVEL_DOCUMENT_TYPES),
            DocumentRenameItemModel.status != "rejected",
            DocumentRenameItemModel.storage_key != "",
            *_batch_filters(current_user, agency_id),
        )
    )
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Renamed document was not found"
        )
    storage_key = item.storage_key
    renamed_filename = item.renamed_filename
    await session.rollback()
    content = await MinioStorageRepository().get_file(storage_key)
    quoted = quote(renamed_filename)
    return Response(
        content,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quoted}",
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, no-store",
        },
    )


@router.get("/batches/{batch_id}/download.zip")
async def download_renamed_zip(
    batch_id: uuid.UUID,
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> StreamingResponse:
    agency_id = _ensure_allowed(current_user)
    batch_result = await session.execute(
        select(DocumentRenameBatchModel).where(
            DocumentRenameBatchModel.id == batch_id,
            *_batch_filters(current_user, agency_id),
        )
    )
    batch = batch_result.scalar_one_or_none()
    if not batch:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Rename batch was not found"
        )
    if getattr(batch, "status", "completed") != "completed":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This rename upload is still processing",
        )
    items_result = await session.execute(
        select(DocumentRenameItemModel)
        .where(
            DocumentRenameItemModel.batch_id == batch.id,
            DocumentRenameItemModel.agency_id == agency_id,
            DocumentRenameItemModel.detected_type.in_(SUPPORTED_TRAVEL_DOCUMENT_TYPES),
            DocumentRenameItemModel.status != "rejected",
            DocumentRenameItemModel.storage_key != "",
        )
        .order_by(DocumentRenameItemModel.created_at.asc())
    )
    items = [
        (
            item.id,
            item.detected_type,
            item.status,
            item.storage_key,
            item.renamed_filename,
        )
        for item in items_result.scalars().all()
    ]
    resolved_batch_id = batch.id
    await session.rollback()
    if not items:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="This batch has no verified visa or flight-ticket PDFs to download.",
        )
    downloadable_items = [
        item
        for item in items
        if item[1] in SUPPORTED_TRAVEL_DOCUMENT_TYPES
        and item[2] != "rejected"
        and bool(item[3])
    ]
    if not downloadable_items:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="This batch has no verified visa or flight-ticket PDFs to download.",
        )
    if not _RENAME_ARCHIVE_ADMISSION.acquire(blocking=False):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="A large renamed ZIP is already being prepared; retry shortly",
            headers={"Retry-After": "30"},
        )
    archive: BinaryIO | None = None
    total_uncompressed_bytes = 0
    try:
        storage = MinioStorageRepository()
        active_archive = cast(
            BinaryIO,
            SpooledTemporaryFile(max_size=16 * 1024 * 1024, mode="w+b"),
        )
        archive = active_archive
        with zipfile.ZipFile(
            active_archive,
            "w",
            compression=zipfile.ZIP_STORED,
            allowZip64=True,
        ) as zip_file:
            used: set[str] = set()
            for offset in range(
                0,
                len(downloadable_items),
                RENAME_ARCHIVE_FETCH_BATCH_SIZE,
            ):
                item_batch = downloadable_items[
                    offset : offset + RENAME_ARCHIVE_FETCH_BATCH_SIZE
                ]
                contents = await _fetch_rename_archive_batch(storage, item_batch)
                for item, content in zip(item_batch, contents, strict=True):
                    item_id, _, _, _, renamed_filename = item
                    total_uncompressed_bytes += len(content)
                    if total_uncompressed_bytes > MAX_RENAME_ARCHIVE_UNCOMPRESSED_BYTES:
                        raise HTTPException(
                            status_code=413,
                            detail="The renamed ZIP exceeds the 512 MB safety limit",
                        )
                    filename = renamed_filename
                    if filename in used:
                        stem = filename[:-4] if filename.lower().endswith(".pdf") else filename
                        filename = f"{stem}_{item_id.hex[:6]}.pdf"
                    used.add(filename)
                    await asyncio.to_thread(zip_file.writestr, filename, content)
        active_archive.seek(0, 2)
        archive_size = active_archive.tell()
        active_archive.seek(0)
    except BaseException:
        if archive is not None:
            archive.close()
        _RENAME_ARCHIVE_ADMISSION.release()
        raise
    assert archive is not None
    zip_name = f"renamed-documents-{resolved_batch_id}.zip"
    try:
        response = StreamingResponse(
            _stream_archive(archive, release_admission=True),
            media_type="application/zip",
            headers={
                "Content-Disposition": f'attachment; filename="{zip_name}"',
                "Content-Length": str(archive_size),
                "X-Content-Type-Options": "nosniff",
                "Cache-Control": "private, no-store",
            },
        )
    except BaseException:
        archive.close()
        _RENAME_ARCHIVE_ADMISSION.release()
        raise
    return response
