"""Document rename routes."""

from __future__ import annotations

import re
import uuid
import zipfile
from datetime import datetime, timezone
from io import BytesIO
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import Response, StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.entities import User, UserRole
from app.infrastructure.database.models import DocumentRenameBatchModel, DocumentRenameItemModel
from app.infrastructure.database.session import get_db_session
from app.infrastructure.documents.document_matcher import DocumentMatcher
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.infrastructure.storage.minio_repository import MinioStorageRepository
from app.presentation.api.v1.schemas.document_rename_schemas import (
    DeleteRenameBatchesRequest,
    DeleteRenameBatchesResponse,
    RenameDocumentBatchResponse,
    RenameDocumentBatchSummaryResponse,
    RenameDocumentItemResponse,
)
from app.presentation.dependencies.auth import get_current_active_user

router = APIRouter()


def _ensure_allowed(current_user: User) -> uuid.UUID:
    if not current_user.agency_id or current_user.role == UserRole.AGENCY_COORDINATOR:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
    return current_user.agency_id


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


def _item_response(item: DocumentRenameItemModel) -> RenameDocumentItemResponse:
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
        download_url=f"/api/v1/document-rename/items/{item.id}/download",
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
        select(DocumentRenameBatchModel).where(
            DocumentRenameBatchModel.id.in_(batch_ids),
            *_batch_filters(current_user, agency_id),
        )
    )
    batches = list(batch_result.scalars().all())
    if not batches:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No rename batches were found")

    found_batch_ids = [batch.id for batch in batches]
    items_result = await session.execute(
        select(DocumentRenameItemModel).where(
            DocumentRenameItemModel.batch_id.in_(found_batch_ids),
            DocumentRenameItemModel.agency_id == agency_id,
        )
    )
    items = list(items_result.scalars().all())
    storage_keys = [item.storage_key for item in items]
    deleted_storage_objects = await MinioStorageRepository().delete_files(storage_keys)

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
            "deleted_storage_objects": deleted_storage_objects,
        },
    )
    await session.commit()
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
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rename batch was not found")
    items_result = await session.execute(
        select(DocumentRenameItemModel)
        .where(DocumentRenameItemModel.batch_id == batch.id)
        .order_by(DocumentRenameItemModel.renamed_filename.asc())
    )
    return await _batch_response(batch, list(items_result.scalars().all()))


@router.post("/batches", response_model=RenameDocumentBatchResponse, status_code=status.HTTP_201_CREATED)
async def analyze_and_rename_documents(
    files: list[UploadFile] = File(...),
    title: str = Form(...),
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> RenameDocumentBatchResponse:
    agency_id = _ensure_allowed(current_user)
    if not files:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Upload at least one PDF")
    title = " ".join(title.split())[:160]
    if not title:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Enter a title for this rename batch")

    matcher = DocumentMatcher()
    storage = MinioStorageRepository()
    now = datetime.now(tz=timezone.utc)
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
    session.add(batch)
    await session.flush()

    used_names: set[str] = set()
    items: list[DocumentRenameItemModel] = []
    for file in files:
        content = await file.read()
        original_filename = file.filename or "document.pdf"
        classification = matcher.classify(filename=original_filename, content=content, expected_type="other")
        detected_type = classification.detected_type if classification.detected_type in {"visa", "flight_ticket"} else "unknown"
        renamed_filename = _renamed_filename(classification.extracted_name, detected_type, used_names)
        document_id = uuid.uuid4()
        storage_key = f"document-rename/{batch.id}/{document_id}-{_safe_part(original_filename)}"
        await storage.upload_file(content, storage_key, file.content_type or "application/pdf")
        reason = _reason(classification.extracted_name, detected_type)
        item = DocumentRenameItemModel(
            id=document_id,
            batch_id=batch.id,
            agency_id=agency_id,
            original_filename=original_filename,
            renamed_filename=renamed_filename,
            storage_key=storage_key,
            content_type=file.content_type or "application/pdf",
            detected_type=detected_type,
            extracted_name=classification.extracted_name,
            extracted_passport_number=classification.extracted_passport_number,
            extracted_reference=classification.extracted_reference,
            status="renamed" if reason is None else "needs_review",
            reason=reason,
            created_at=now,
            updated_at=now,
        )
        items.append(item)
        session.add(item)

    batch.total_count = len(items)
    batch.visa_count = sum(1 for item in items if item.detected_type == "visa")
    batch.ticket_count = sum(1 for item in items if item.detected_type == "flight_ticket")
    batch.unknown_count = sum(1 for item in items if item.detected_type == "unknown")
    await AuditLogRepository(session).record(
        action="document_rename_completed",
        entity_type="document_rename_batch",
        entity_id=str(batch.id),
        agency_id=agency_id,
        user_id=current_user.id,
        actor_email=current_user.email,
        metadata={
            "total_count": batch.total_count,
            "visa_count": batch.visa_count,
            "ticket_count": batch.ticket_count,
            "unknown_count": batch.unknown_count,
        },
    )
    await session.commit()
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
        .join(DocumentRenameBatchModel, DocumentRenameBatchModel.id == DocumentRenameItemModel.batch_id)
        .where(
            DocumentRenameItemModel.id == item_id,
            DocumentRenameItemModel.agency_id == agency_id,
            *_batch_filters(current_user, agency_id),
        )
    )
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Renamed document was not found")
    content = await MinioStorageRepository().get_file(item.storage_key)
    quoted = quote(item.renamed_filename)
    return Response(
        content,
        media_type=item.content_type,
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quoted}"},
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
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rename batch was not found")
    items_result = await session.execute(
        select(DocumentRenameItemModel)
        .where(DocumentRenameItemModel.batch_id == batch.id)
        .order_by(DocumentRenameItemModel.created_at.asc())
    )
    items = list(items_result.scalars().all())
    storage = MinioStorageRepository()
    archive = BytesIO()
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as zip_file:
        used: set[str] = set()
        for item in items:
            filename = item.renamed_filename
            if filename in used:
                stem = filename[:-4] if filename.lower().endswith(".pdf") else filename
                filename = f"{stem}_{item.id.hex[:6]}.pdf"
            used.add(filename)
            zip_file.writestr(filename, await storage.get_file(item.storage_key))
    archive.seek(0)
    zip_name = f"renamed-documents-{batch.id}.zip"
    return StreamingResponse(
        archive,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{zip_name}"'},
    )
