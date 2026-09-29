"""Canonical document-review workbook without presigned URLs or provider reads."""

from __future__ import annotations

import asyncio
import uuid
from collections import defaultdict
from dataclasses import dataclass, fields
from typing import Any, Literal

from app.application.mcp.document_export_source import DocumentExcelSupport, DocumentExportSource
from app.application.use_cases.passports.excel_snapshot import snapshot_digest
from app.domain.value_objects.travel_document_taxonomy import document_type_label
from app.infrastructure.documents.storage_transfers import run_bounded_storage_operations
from app.infrastructure.export.document_assignment_excel_exporter import (
    _excel_text,
    build_document_assignment_workbook,
)
from app.infrastructure.export.workbook_capacity import WorkbookCapacityError

DocumentReviewFilter = Literal["all", "assigned", "missing", "sent", "not_sent", "multiple_pdfs"]
MAX_CELL_CHARACTERS = 32767
_FILTER_LABELS = {
    "all": "All",
    "assigned": "Assigned",
    "missing": "Missing",
    "sent": "Sent",
    "not_sent": "Not sent",
    "multiple_pdfs": "Multiple PDFs",
}


@dataclass(frozen=True)
class PreparedDocumentWorkbook:
    arguments: dict[str, Any]
    filename: str
    revision: str
    passenger_count: int
    assignment_count: int
    exported_count: int

    async def render(self, *, maximum_output_bytes: int) -> bytes:
        def build() -> bytes:
            with build_document_assignment_workbook(
                **self.arguments, maximum_output_bytes=maximum_output_bytes
            ) as stream:
                return stream.getvalue()

        return (
            await run_bounded_storage_operations([lambda: asyncio.to_thread(build)], concurrency=1)
        )[0]


def prepare_document_workbook(
    *,
    support: DocumentExcelSupport,
    source: DocumentExportSource,
    group_name: str,
    document_type: str,
    review_filter: DocumentReviewFilter,
    search: str,
    maximum_snapshot_bytes: int,
) -> PreparedDocumentWorkbook:
    deliveries: dict[uuid.UUID, list[Any]] = defaultdict(list)
    for row in source.deliveries:
        deliveries[row.distributed_document_id].append(row)
    responses = {
        row.id: support.document_response(row, source="manual", deliveries=deliveries[row.id])
        for row in source.documents
    }
    review, _unmatched, _count = support.review_rows(
        passengers=source.passengers, documents=source.documents, responses_by_document=responses
    )
    rows = support.export_rows(review, review_filter=review_filter, search_query=search)
    # Reject before XLSX silently truncates a long joined list for one passenger.
    if any(
        len(_excel_text(getattr(row, field.name))) > MAX_CELL_CHARACTERS
        for row in rows
        for field in fields(row)
    ):
        raise WorkbookCapacityError("Document review exceeds the spreadsheet cell text limit")
    arguments = dict(
        group_name=group_name,
        document_label=document_type_label(document_type),
        filter_label=_FILTER_LABELS[review_filter],
        search_query=search,
        rows=rows,
    )
    revision = snapshot_digest(
        {"source": source.snapshot, "arguments": arguments}, maximum_bytes=maximum_snapshot_bytes
    )
    filename = (
        support.filename(f"{group_name}-{document_type}-{review_filter}-document-assignments")
        + ".xlsx"
    )
    return PreparedDocumentWorkbook(
        arguments, filename, revision, len(source.passengers), len(source.documents), len(rows)
    )
