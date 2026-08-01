"""Document rename routes."""

from __future__ import annotations

import asyncio
import re
import uuid
import zipfile
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from tempfile import SpooledTemporaryFile
from typing import BinaryIO
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import Response, StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging.logger import get_logger
from app.domain.entities.entities import User, UserRole
from app.infrastructure.database.models import (
    AgencyModel,
    DocumentRenameBatchModel,
    DocumentRenameItemModel,
    UserModel,
)
from app.infrastructure.database.session import get_db_session
from app.infrastructure.documents.document_matcher import (
    SUPPORTED_TRAVEL_DOCUMENT_TYPES,
    DocumentMatcher,
    DocumentParserUnavailableError,
    classify_documents_bounded,
)
from app.infrastructure.documents.storage_cleanup import (
    persist_storage_cleanup_job,
    process_storage_cleanup_job,
    stage_storage_cleanup_jobs,
)
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.infrastructure.storage.minio_repository import MinioStorageRepository
from app.presentation.api.v1.document_uploads import read_bounded_document_uploads
from app.presentation.api.v1.schemas.document_rename_schemas import (
    DeleteRenameBatchesRequest,
    DeleteRenameBatchesResponse,
    RenameDocumentBatchResponse,
    RenameDocumentBatchSummaryResponse,
    RenameDocumentItemResponse,
)
from app.presentation.dependencies.auth import get_current_active_user

router = APIRouter()
logger = get_logger(__name__)


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
) -> UserModel:
    """Re-authorize the actor and agency inside the short write transaction."""

    result = await session.execute(
        select(UserModel)
        .join(AgencyModel, AgencyModel.id == UserModel.agency_id)
        .where(
            UserModel.id == user_id,
            UserModel.agency_id == agency_id,
            UserModel.is_active.is_(True),
            UserModel.deleted_at.is_(None),
            UserModel.role != UserRole.AGENCY_COORDINATOR.value,
            AgencyModel.is_active.is_(True),
        )
        .with_for_update(of=(UserModel, AgencyModel))
        .execution_options(populate_existing=True)
    )
    actor = result.scalar_one_or_none()
    if actor is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your account or agency is no longer authorized for document rename.",
        )
    return actor


def _batch_filters(current_user: User, agency_id: uuid.UUID) -> list:
    filters = [DocumentRenameBatchModel.agency_id == agency_id]
    if current_user.role == UserRole.AGENCY_STAFF:
        filters.append(DocumentRenameBatchModel.created_by_user_id == current_user.id)
    return filters


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


async def _stream_archive(archive: BinaryIO) -> AsyncIterator[bytes]:
    try:
        while chunk := await asyncio.to_thread(archive.read, 64 * 1024):
            yield chunk
    finally:
        archive.close()


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


@router.post("/batches/bulk-delete", response_model=DeleteRenameBatchesResponse)
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
    storage_keys = list({item.storage_key for item in items if item.storage_key})
    cleanup_jobs = stage_storage_cleanup_jobs(
        session,
        agency_id=agency_id,
        source="document_rename_batch_delete",
        context_id=",".join(str(batch_id) for batch_id in sorted(found_batch_ids, key=str)),
        storage_keys=storage_keys,
    )

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
    "/batches", response_model=RenameDocumentBatchResponse, status_code=status.HTTP_201_CREATED
)
async def analyze_and_rename_documents(
    files: list[UploadFile] = File(...),
    title: str = Form(...),
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> RenameDocumentBatchResponse:
    agency_id = _ensure_allowed(current_user)
    actor_id = current_user.id
    title = " ".join(title.split())[:160]
    if not title:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Enter a title for this rename batch"
        )

    # Authentication uses this request session and may have opened a read
    # transaction. Release it before bounded upload reads, PDF parsing, and
    # object storage; authorization is repeated under lock before DB staging.
    await session.rollback()
    uploads = await read_bounded_document_uploads(files)
    matcher = DocumentMatcher()
    storage = MinioStorageRepository()
    now = datetime.now(tz=UTC)
    batch = DocumentRenameBatchModel(
        id=uuid.uuid4(),
        agency_id=agency_id,
        title=title,
        status="completed",
        total_count=0,
        visa_count=0,
        ticket_count=0,
        unknown_count=0,
        created_by_user_id=current_user.id,
        created_at=now,
        updated_at=now,
    )
    used_names: set[str] = set()
    items: list[DocumentRenameItemModel] = []
    uploaded_keys: list[str] = []
    try:
        classifications = await asyncio.to_thread(
            classify_documents_bounded,
            matcher,
            [(upload.filename, upload.content, "other") for upload in uploads],
            isolate_pdf_parsing=True,
        )
    except DocumentParserUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
            headers={"Retry-After": "1"},
        ) from exc
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
                    f"document-rename/{batch.id}/{document_id}-{_safe_part(upload.filename)}"
                )
                uploaded_keys.append(storage_key)
                await storage.upload_file(upload.content, storage_key, "application/pdf")
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
                batch_id=batch.id,
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
    except Exception:
        await _cleanup_owned_rename_storage(
            storage,
            uploaded_keys,
            agency_id=agency_id,
            batch_id=batch.id,
        )
        raise

    try:
        actor = await _lock_active_rename_actor(
            session,
            user_id=actor_id,
            agency_id=agency_id,
        )
        batch.total_count = len(items)
        batch.visa_count = sum(1 for item in items if item.detected_type == "visa")
        batch.ticket_count = sum(1 for item in items if item.detected_type == "flight_ticket")
        batch.unknown_count = sum(1 for item in items if item.detected_type == "unknown")
        session.add(batch)
        for item in items:
            session.add(item)
        await AuditLogRepository(session).record(
            action="document_rename_completed",
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
            },
        )
        await session.flush()
    except Exception:
        await session.rollback()
        await _cleanup_owned_rename_storage(
            storage,
            uploaded_keys,
            agency_id=agency_id,
            batch_id=batch.id,
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
            batch_id=str(batch.id),
            object_count=len(uploaded_keys),
        )
        raise
    return await _batch_response(batch, items)


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
    storage = MinioStorageRepository()
    archive = SpooledTemporaryFile(max_size=16 * 1024 * 1024, mode="w+b")
    try:
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as zip_file:
            used: set[str] = set()
            for item_id, detected_type, item_status, storage_key, renamed_filename in items:
                if (
                    detected_type not in SUPPORTED_TRAVEL_DOCUMENT_TYPES
                    or item_status == "rejected"
                    or not storage_key
                ):
                    continue
                filename = renamed_filename
                if filename in used:
                    stem = filename[:-4] if filename.lower().endswith(".pdf") else filename
                    filename = f"{stem}_{item_id.hex[:6]}.pdf"
                used.add(filename)
                content = await storage.get_file(storage_key)
                await asyncio.to_thread(zip_file.writestr, filename, content)
        archive.seek(0)
    except Exception:
        archive.close()
        raise
    zip_name = f"renamed-documents-{resolved_batch_id}.zip"
    return StreamingResponse(
        _stream_archive(archive),
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{zip_name}"',
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, no-store",
        },
    )
