"""Assignment review filters and ordered spreadsheet rows."""

from __future__ import annotations

from typing import Literal

from app.infrastructure.export.document_assignment_excel_exporter import DocumentAssignmentExportRow
from app.presentation.api.v1.schemas.document_distribution_schemas import (
    DistributedDocumentResponse,
    DocumentPassengerReviewRow,
)

DocumentAssignmentExportFilter = Literal[
    "all",
    "assigned",
    "missing",
    "sent",
    "not_sent",
    "multiple_pdfs",
    "shared_pdf",
]

_SENT_DOCUMENT_STATUSES = frozenset({"submitted", "sent", "delivered", "read"})


def _joined_document_values(values: list[object]) -> str:
    return "\n".join(dict.fromkeys(str(value).strip() for value in values if value))


def _assignment_export_matches_filter(
    row: DocumentPassengerReviewRow,
    documents: list[DistributedDocumentResponse],
    pdf_count: int,
    assigned: bool,
    review_filter: DocumentAssignmentExportFilter,
) -> bool:
    sent = any(document.delivery_status in _SENT_DOCUMENT_STATUSES for document in documents)
    not_sent = any(
        document.delivery_status not in _SENT_DOCUMENT_STATUSES for document in documents
    )
    if review_filter == "assigned" and not assigned:
        return False
    if review_filter == "missing" and assigned:
        return False
    if review_filter == "sent" and not sent:
        return False
    if review_filter == "not_sent" and not not_sent:
        return False
    if review_filter == "multiple_pdfs" and pdf_count <= 1:
        return False
    if review_filter == "shared_pdf" and row.shared_pdf_count == 0:
        return False
    return True


def _assignment_export_row(
    row: DocumentPassengerReviewRow,
    documents: list[DistributedDocumentResponse],
    pdf_count: int,
    assigned: bool,
) -> DocumentAssignmentExportRow:
    return DocumentAssignmentExportRow(
        passenger_name=row.passenger_name,
        passport_number=row.passport_number or "",
        departure_city=row.departure_city or "",
        assignment_status="Assigned" if assigned else "Missing",
        document_count=pdf_count,
        document_filenames=_joined_document_values(
            [document.original_filename for document in documents]
        ),
        match_statuses=_joined_document_values([document.match_status for document in documents]),
        match_confidences=_joined_document_values(
            [f"{document.match_confidence:.0%}" for document in documents]
        ),
        delivery_statuses=_joined_document_values(
            [document.delivery_status for document in documents]
        ),
        sent_to=_joined_document_values([document.sent_to for document in documents]),
        last_sent_at=_joined_document_values([document.last_sent_at for document in documents]),
        match_reasons=_joined_document_values([document.match_reason for document in documents]),
    )


def _document_assignment_export_rows(
    rows: list[DocumentPassengerReviewRow],
    *,
    review_filter: DocumentAssignmentExportFilter,
    search_query: str,
) -> list[DocumentAssignmentExportRow]:
    normalized_search = search_query.strip().casefold()
    export_rows: list[DocumentAssignmentExportRow] = []
    for row in rows:
        if normalized_search and normalized_search not in row.passenger_name.casefold():
            continue
        documents = row.documents or ([row.document] if row.document is not None else [])
        pdf_count = row.assigned_pdf_count
        if pdf_count is None:
            pdf_count = len(
                {document.id for document in documents if document.match_status == "matched"}
            )
        assigned = bool(documents)
        if not _assignment_export_matches_filter(
            row, documents, pdf_count, assigned, review_filter
        ):
            continue
        export_rows.append(_assignment_export_row(row, documents, pdf_count, assigned))
    return export_rows


_joined_document_values.__module__ = (
    "app.presentation.api.v1.routes.document_distribution_review_support"
)
_document_assignment_export_rows.__module__ = (
    "app.presentation.api.v1.routes.document_distribution_review_support"
)
