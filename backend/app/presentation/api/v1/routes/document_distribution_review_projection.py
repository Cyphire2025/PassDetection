"""Passenger and physical-file review accounting."""

from __future__ import annotations

import uuid

from app.domain.entities.entities import PassportSubmission
from app.infrastructure.database.models import DistributedDocumentModel
from app.presentation.api.v1.schemas.document_distribution_schemas import (
    DistributedDocumentResponse,
    DocumentAssignmentIssueResponse,
    DocumentPassengerReviewRow,
)


def _passport_number(passenger: PassportSubmission) -> str | None:
    fields = passenger.confirmed_fields or passenger.extracted_fields or {}
    value = fields.get("passport_number")
    return str(value).strip() if value else None


def _passenger_review_rows(
    *,
    passengers: list[PassportSubmission],
    documents: list[DistributedDocumentModel],
    responses_by_document: dict[uuid.UUID, DistributedDocumentResponse],
) -> tuple[
    list[DocumentPassengerReviewRow],
    list[DistributedDocumentResponse],
    int,
]:
    """Group the persistent document ledger into one row per submitted passenger."""

    passenger_ids = {passenger.id for passenger in passengers}
    docs_by_passenger: dict[uuid.UUID, list[DistributedDocumentModel]] = {}
    passengers_by_file: dict[str, set[uuid.UUID]] = {}
    unmatched: list[DistributedDocumentResponse] = []
    for document in documents:
        if document.match_status == "superseded":
            continue
        if document.passenger_id in passenger_ids:
            docs_by_passenger.setdefault(document.passenger_id, []).append(document)
            if document.match_status == "matched":
                key = str(getattr(document, "storage_key", "") or document.id)
                passengers_by_file.setdefault(key, set()).add(document.passenger_id)
        else:
            unmatched.append(responses_by_document[document.id])

    rows: list[DocumentPassengerReviewRow] = []
    matched_passenger_count = 0
    for passenger in passengers:
        passenger_documents = docs_by_passenger.get(passenger.id, [])
        rendered_documents = [
            responses_by_document[document.id] for document in passenger_documents
        ]
        if any(document.match_status == "matched" for document in passenger_documents):
            matched_passenger_count += 1
        rows.append(
            DocumentPassengerReviewRow(
                passenger_id=passenger.id,
                passenger_name=getattr(passenger, "display_name", None) or passenger.client_name,
                passport_number=_passport_number(passenger),
                departure_city=passenger.departure_city,
                document=rendered_documents[0] if rendered_documents else None,
                documents=rendered_documents,
                assigned_pdf_count=len(
                    {
                        str(getattr(document, "storage_key", "") or document.id)
                        for document in passenger_documents
                        if document.match_status == "matched"
                    }
                ),
                shared_pdf_count=len(
                    {
                        str(getattr(document, "storage_key", "") or document.id)
                        for document in passenger_documents
                        if document.match_status == "matched"
                        and len(
                            passengers_by_file.get(
                                str(getattr(document, "storage_key", "") or document.id), set()
                            )
                        )
                        > 1
                    }
                ),
            )
        )

    return rows, unmatched, matched_passenger_count


def _physical_file_accounting(
    *,
    passengers: list[PassportSubmission],
    documents: list[DistributedDocumentModel],
    responses_by_document: dict[uuid.UUID, DistributedDocumentResponse],
) -> tuple[int, int, int, list[DocumentAssignmentIssueResponse]]:
    """Count stored PDFs independently from their assignment rows.

    A combined PDF can intentionally create several rows that share one
    storage key, while several PDFs can be assigned to the same passenger.
    Grouping by the server-generated storage key keeps both cases truthful.
    """

    passenger_ids = {passenger.id for passenger in passengers}
    physical_documents: dict[str, list[DistributedDocumentModel]] = {}
    for document in documents:
        if document.match_status == "superseded":
            continue
        storage_identity = str(getattr(document, "storage_key", "") or document.id)
        physical_documents.setdefault(storage_identity, []).append(document)

    assigned_files = 0
    assigned_passengers: set[uuid.UUID] = set()
    issues: list[DocumentAssignmentIssueResponse] = []
    for grouped_documents in physical_documents.values():
        valid_assignments = [
            document
            for document in grouped_documents
            if document.match_status == "matched" and document.passenger_id in passenger_ids
        ]
        if valid_assignments:
            assigned_files += 1
            assigned_passengers.update(
                document.passenger_id
                for document in valid_assignments
                if document.passenger_id is not None
            )
            continue

        representative = grouped_documents[0]
        response = responses_by_document[representative.id]
        if any(
            document.passenger_id is not None and document.passenger_id not in passenger_ids
            for document in grouped_documents
        ):
            code = "passenger_no_longer_in_group"
            reason = "The previously matched passenger is no longer in this group."
        elif any(document.match_status == "duplicate_document" for document in grouped_documents):
            code = "duplicate_document"
            reason = response.match_reason or "This PDF duplicates an existing saved document."
        else:
            code = "no_unique_passenger_match"
            reason = response.match_reason or "No unique passenger match was found."
        issues.append(
            DocumentAssignmentIssueResponse(
                document_id=response.id,
                original_filename=response.original_filename,
                code=code,
                reason=reason,
                url=response.url,
            )
        )

    return len(physical_documents), assigned_files, len(assigned_passengers), issues


_passport_number.__module__ = "app.presentation.api.v1.routes.document_distribution_review_support"
_passenger_review_rows.__module__ = (
    "app.presentation.api.v1.routes.document_distribution_review_support"
)
_physical_file_accounting.__module__ = (
    "app.presentation.api.v1.routes.document_distribution_review_support"
)
