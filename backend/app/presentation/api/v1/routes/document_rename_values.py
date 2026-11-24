"""Document rename names and public response projections."""

from __future__ import annotations

import re

from app.application.use_cases.document_rename.read_scope import (
    download_metadata_eligible,
)
from app.domain.entities.entities import UserRole
from app.infrastructure.database.models import (
    DocumentRenameBatchModel,
    DocumentRenameItemModel,
)
from app.presentation.api.v1.schemas.document_rename_schemas import (
    RenameDocumentBatchResponse,
    RenameDocumentBatchSummaryResponse,
    RenameDocumentItemResponse,
)


def _role_value(role: UserRole | str) -> str:
    return role.value if isinstance(role, UserRole) else role


def _document_label(detected_type: str) -> str:
    if detected_type == "visa":
        return "VISA"
    if detected_type == "flight_ticket":
        return "TICKET"
    return "DOCUMENT"


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
    downloadable = download_metadata_eligible(
        item.detected_type, item.status, bool(item.storage_key)
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
