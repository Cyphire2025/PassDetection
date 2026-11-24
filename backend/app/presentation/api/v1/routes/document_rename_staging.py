"""Classify PDFs and stage only supported private objects with compensation."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime

from fastapi import HTTPException, status

from app.domain.value_objects.travel_document_taxonomy import (
    SUPPORTED_TRAVEL_DOCUMENT_TYPES,
)
from app.infrastructure.database.models import (
    DocumentRenameBatchModel,
    DocumentRenameItemModel,
)
from app.infrastructure.documents.document_matcher import (
    DocumentParserUnavailableError,
    UnsupportedDocumentBatchFormatError,
)
from app.infrastructure.documents.pdf_parser_sandbox import (
    bounded_pdf_batch_timeout_seconds,
)
from app.infrastructure.documents.storage_transfers import (
    finish_cleanup_despite_cancellation,
    run_bounded_storage_operations,
)
from app.presentation.api.v1.routes.document_rename_upload_contracts import (
    PreparedRenameUpload,
    RenameStorageServices,
    StagedRenameUpload,
)
from app.presentation.api.v1.routes.document_rename_values import (
    _reason,
    _renamed_filename,
    _safe_part,
)


async def stage_rename_storage(
    prepared: PreparedRenameUpload,
    *,
    services: RenameStorageServices,
) -> StagedRenameUpload:
    agency_id = prepared.agency_id
    actor_id = prepared.actor_id
    title = prepared.title
    chunk_metadata = prepared.chunk_metadata
    uploads = prepared.uploads
    batch_id = prepared.batch_id
    existing_batch = prepared.existing_batch
    used_names = prepared.used_names
    matcher = services.matcher_factory()
    storage = services.storage_factory()
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
            bounded_pdf_batch_timeout_seconds(len(uploads)) if chunk_metadata is not None else None
        )
        classifications = await asyncio.to_thread(
            services.classify,
            matcher,
            [(upload.filename, upload.content, "other") for upload in uploads],
            isolate_pdf_parsing=True,
            batch_timeout_seconds=parser_timeout,
            reject_common_unsupported_format=True,
        )
    except UnsupportedDocumentBatchFormatError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
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
                    classification.extracted_name, detected_type, used_names
                )
                storage_key = (
                    f"document-rename/{batch_id}/{document_id}-{_safe_part(upload.filename)}"
                )
                uploaded_keys.append(storage_key)
                storage_operations.append(
                    lambda payload=upload.content, key=storage_key: storage.upload_file(
                        payload, key, "application/pdf"
                    )
                )
                reason = _reason(classification.extracted_name, detected_type)
                item_status = "renamed" if reason is None else "needs_review"
            else:
                # Keep review metadata, never rejected bytes or extracted PII.
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
                extracted_passport_number=classification.extracted_passport_number
                if supported
                else None,
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
            services.cleanup(storage, uploaded_keys, agency_id=agency_id, batch_id=batch_id)
        )
        raise
    return StagedRenameUpload(batch, items, uploaded_keys, storage, now)
